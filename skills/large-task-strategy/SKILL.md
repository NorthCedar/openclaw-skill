---
name: large-task-strategy
description: >
  Execute large tasks (code reading, documentation, refactoring, debugging, K8s/DB queries)
  that exceed a single context window or require >30s steps, using sub-agent orchestration with incremental
  persistence. Use when: (1) reading/analyzing >500 lines of code, (2) writing documentation from large
  codebases, (3) any task requiring >10 minutes with multiple files, (4) bulk refactoring across many files,
  (5) debugging/investigation tasks with multiple query steps, (6) any task where a single step takes >30s.
---

# Large Task Strategy

## Why

解决三个核心问题:
1. **上下文过载** - 单个 agent 无法处理超大代码库/文档/数据源
2. **主进程阻塞** - 耗时操作占用主进程,导致无法响应用户
3. **单一视角局限** - 复杂问题需要多角色(如安全审计+性能分析+可读性审查)从不同维度优化

## Architecture: Flat Multi-Fork Tree

```
整体结构:扁平多叉树

         主进程(根节点 = 唯一调度者)
        /    |    |    \
      A      B    C    D(第1轮子进程)
     ✔️     ✔️   ✔️   ⚠️ NEEDS_SPLIT
                       |
                  主进程读取拆分建议,重新派发
                   /    |    \
                 D1    D2    D3(第2轮子进程)
                 ✔️    ✔️    ✔️
```

**节点角色:**
- **主进程**(根节点):唯一调度者,拥有所有派发权
- **子进程(叶子节点)**:直接完成任务,输出产出文件
- **子进程(子树根节点)**:发现任务需拆分,输出拆分建议并回报主进程--主进程读取建议后再派新子进程

**核心约束:**
- 调度权始终在主进程,子进程只有「判断权」(是否需拆分),没有「派发权」
- 树的生长由主进程驱动,不由子进程自主扩展
- 同一轮的子进程互不依赖,可并行执行

### 子进程两种用法

| 用法 | 场景 | 例子 |
|------|------|------|
| 分段并行 | 任务可拆分为独立子任务,每个处理一段 | 读 3000 行代码,5 个 agent 各读 600 行 |
| 多角色审查 | 同一内容需多个视角审视 | 安全 agent + 性能 agent + 可读性 agent 审查同一代码 |

> **Iron triangle: Split small · Persist to disk · Verify output.**

## When to Activate

- Reading/analyzing > 2 files or > 500 lines of code
- Task estimated > 10 minutes
- Need to spawn sub-agents
- **Any single step estimated > 30 seconds**
- **Any task with ≥2 independent steps** that can be parallelized
- Debug/investigation with multiple data sources
- **When in doubt, activate** - better to over-persist than lose work

## Core Principles

1. **Anything in your brain must be written to a file ASAP. Unwritten = unread.**
2. **调度权集中** - 只有主进程可以 spawn 子进程。子进程只能回报拆分建议,不得自行派发。
3. **Token 最小化** - 共享知识走磁盘,不走 task 文本。
4. **子进程有判断权,无派发权** - 子进程首先确认任务、评估是否需拆分。需拆分时回报主进程,由主进程决策和派发。
5. **shared.md = 任务注册表** - 全局唯一协调文件,只含任务上下文 + 拆分 + 状态追踪,写入需加锁。

---

## Dispatch Flow (调度流程)

### 正常流程（叶子节点）

```
主进程第1轮: 派 agent A、B、C（并行，各读 ≤300 行）
  ↓ 等完成 + 验证产出
主进程第2轮: 基于 A/B/C 产出，派 agent D、E（依赖前者）
  ↓ 等完成 + 验证产出
主进程第3轮: 合并验证 → 输出最终结果
```

### NEEDS_SPLIT 流程（子树生长）

```
主进程派 agent-d（侦察任务）
  ↓ agent-d 评估后发现任务过大
  ↓ agent-d 写拆分建议到 agent-d.md，标记 ## NEEDS_SPLIT
  ↓ agent-d 回写 shared.md 状态为 ⚠️ needs_split
主进程读取 agent-d.md 中的拆分建议
  ↓ 注册新条目 agent-d1、agent-d2、agent-d3
  ↓ 派发新子进程执行
```

### 多角色审查流程

```
主进程同时派:
  agent-security（安全视角审查 /path/api.go）
  agent-perf（性能视角审查 /path/api.go）
  agent-readability（可读性视角审查 /path/api.go）
  ↓ 各自输出独立分析
主进程合并三个视角的结果 → 综合报告
```

**禁止:**
```
❌ 子进程 A 自行 spawn 孙进程 A1, A2
   （主进程看不到 A1/A2，无法验证，Token 浪费）
```

**多轮调度的好处:**
- 主进程始终可控，可随时终止/重派
- 上下文精确：后轮 agent 按需读取前轮指定产出文件（非全部）
- Token 节省 ~67%（对比嵌套方式）

---

## Phase 0: Output Execution Plan (Mandatory)

Before spawning any sub-agent, output an execution plan:

1. **Steps identified**: what needs to be done
2. **Dependency analysis**: parallel vs sequential(画出轮次)
3. **Sub-agent allocation**: how many, what each one does
4. **Expected timeline**: rough estimate

Send plan to 用户, confirm, then execute.

---

## Phase 0a: Setup (Mandatory)

### Create Task Workspace

每个任务有唯一 ID(`{task-id}` = 简短描述性名称),所有中间文件在隔离目录内:

```bash
TASK_DIR="memory/wip/${TASK_ID}"
mkdir -p "${TASK_DIR}"
```

**目录结构:**
```
memory/wip/{task-id}/
├── shared.md          # 全局共享知识(所有 agent 读)
├── map.md             # 代码骨架/结构地图
├── agent-a.md         # 子 agent A 的产出
├── agent-b.md         # 子 agent B 的产出
├── ...
├── merged.md          # 最终合并结果(可选)
└── .meta.json         # 任务元数据(创建时间、状态、TTL)
```

### Create `.meta.json`(任务元数据)

```json
{
  "taskId": "{task-id}",
  "createdAt": "2026-05-09T15:00:00Z",
  "status": "running",
  "ttlHours": 24,
  "cronName": "{task-id}-keepalive"
}
```

**TTL 保底清理:** 任务超过 `ttlHours` 仍未标记 `completed` 时,下次 heartbeat 检测到会提醒清理。

### Create Cron Keep-Alive (30-second interval)

```bash
openclaw cron add --name {task-id}-keepalive --every 30s --message "HEARTBEAT_OK" --channel last --announce --sessionTarget current
```

**⚠️ CRITICAL: `sessionTarget` must be `current`**
- ❌ Omitting → defaults to `isolated` → original session never wakes
- ❌ `sessionTarget: "main"` in non-main session → wrong session
- ✅ Always `sessionTarget: "current"`

**Delete the cron when the task is complete.**

---

## Phase 1: Reconnaissance (Main Process + Sub-Agents)

### 主进程侦察

Before spawning sub-agents, build a map:

```bash
# Directory structure + line counts
find <path> -name '*.go' -not -name '*_test.go' -exec wc -l {} + | sort -rn

# Key signatures
grep -rn '^func\|^type\|^const\|^var' <path>/*.go
```

Write map to `memory/wip/{task-id}/map.md`. This file stays small (<200 lines).

### 子 agent 自侦察协议(每个 agent 启动时必须执行)

每个子 agent 收到任务后,**首先执行以下判定流程**(不是直接开干):

1. **确认任务** - 读 `shared.md` 中自己对应的任务条目,确认任务范围和预期产出
2. **评估复杂度** - 判断自己的任务是否需要进一步拆分(超过 500 行输入 / 多个独立子步骤)
3. **决策**:
   - ✅ 任务可直接完成 → 执行并输出
   - ⚠️ 任务需要拆分 → **不自行派发子 agent**,而是将拆分建议写入自己的输出文件,标记 `## NEEDS_SPLIT`,主进程读取后重新调度
4. **如果启用 large-task 判定** - 当前 agent 的任务变为「侦察」:分析目标代码结构、评估工作量、输出拆分建议供主进程决策

---

## Phase 1.5: Shared Task Registry (共享任务注册表)

### 目的

1. 作为当前任务的**全局唯一协调文件**,所有 agent 共享读取
2. **只包含:用户任务上下文 + 任务拆分 + agent 关联 + 状态追踪表**
3. **不承载背景知识** - agent 间依赖通过直接读取对方产出文件解决

### 文件:`memory/wip/{task-id}/shared.md`

内容结构(控制在 **≤150 行**):

```markdown
# Task: {task-id}

## Context
用户任务描述(原始需求 1-3 句)
关键约束/规范/输出格式要求

## Task Registry
| Agent | Sub-Task | Input | Output | Depends | Status |
|-------|----------|-------|--------|---------|--------|
| agent-a | 分析 auth 模块 | /path/auth.go:1-300 | agent-a.md | - | 🟡 running |
| agent-b | 分析 handler 模块 | /path/handler.go:1-250 | agent-b.md | - | ⚪ pending |
| agent-c | 合并 auth+handler 分析 | - | agent-c.md | agent-a, agent-b | ⚪ pending |
| agent-d | 侦察:评估 service 层拆分 | /path/service/ | agent-d.md | - | ⚠️ needs_split |
```

### 知识依赖规则

- **shared.md 不写背景知识**,只写任务上下文和注册表
- agent 需要其他 agent 的知识时,**直接读取对方的产出文件**(如 `agent-a.md`)
- 在 Task Registry 的 `Depends` 列标注依赖关系,方便主进程排轮次
- 产出文件归属:**只有本 agent 可写自己的输出文件,其他 agent 只读**

### 状态标记

| 标记 | 含义 |
|------|------|
| ⚪ pending | 已分配,agent 未启动 |
| 🟡 running | agent 已启动执行中 |
| ✅ done | 执行成功,产出已验证 |
| ❌ failed | 执行失败(附原因) |
| ⚠️ needs_split | agent 判定任务需进一步拆分 |

### 并发读写锁机制

共享文件存在并发读写风险,使用文件锁保护:

```bash
# 加锁写入 shared.md(所有写操作必须通过此方式)
LOCK_FILE="memory/wip/{task-id}/.shared.lock"

(
  flock -w 10 200 || { echo "Lock timeout"; exit 1; }
  # --- 临界区开始 ---
  # 使用 awk 精确匹配 agent 名称并修改 Status 列(6列表格的最后一列)
  awk -i inplace '/\| agent-{name} /{sub(/\| [^│]+ \|$/, "| ✅ done |")}1' "memory/wip/{task-id}/shared.md"
  # --- 临界区结束 ---
) 200>"${LOCK_FILE}"
```

**锁规则:**
- 使用 `flock` 文件锁(Linux 原生,无额外依赖)
- 锁文件:`memory/wip/{task-id}/.shared.lock`
- 超时 10 秒(避免死锁)
- **读操作不加锁**(允许脏读,状态最终一致即可)
- **写操作必须加锁**(状态更新、新增条目)
- 主进程写入:分配任务时标记 `🟡 running`
- 子 agent 写入:完成时更新为 `✅ done` / `❌ failed` / `⚠️ needs_split`
- **主进程加锁时机**:如果当前无任何 agent running(如批量注册后还未派发),可不加锁;一旦有 agent 已启动,所有写入都必须 flock

### 产出文件所有权

| 规则 | 说明 |
|------|------|
| 每个 agent 有且仅有一个输出文件 | `memory/wip/{task-id}/agent-{name}.md` |
| 只有本 agent 可写自己的输出文件 | 其他 agent / 主进程只读 |
| 依赖其他 agent 的知识 | 直接 `read` 对方产出文件,不复制到 shared.md |
| 主进程合并阶段 | 读取各 agent 产出文件,写入 `merged.md` |

### 主进程职责

- 启动每个 agent **前**,先在 Task Registry 中注册该 agent 的条目(加锁写入)
- 标注 agent 对应哪个子任务、输入范围、预期输出路径
- 便于子 agent 启动后确认自己的任务、最终结果汇总时定位所有产出

### 子 agent task 引用方式

```
task: |
  先读 `memory/wip/{task-id}/shared.md` 获取背景和你的任务定义(在 Task Registry 中找 agent-{name})。
  确认任务范围后执行。
  产出写入 `memory/wip/{task-id}/agent-{name}.md`。
  完成后加锁更新 shared.md 中你的状态。
```

**效果:** 每个 agent 输入从 ~15k 降到 ~5k token。5 个 agent 总省 ~50k token。共享文件同时作为进度看板,主进程随时可查全局状态。

### 禁止事项

- ❌ 把 shared 内容复制粘贴到 task 文本里(浪费 token)
- ❌ shared.md 超过 150 行(强迫精炼)
- ❌ 不加锁直接写 shared.md
- ❌ 子 agent 修改 Task Registry 中其他 agent 的条目(只能改自己的状态)
- ❌ 在 shared.md 中写背景知识/代码片段(只放任务上下文和注册表)
- ❌ 子 agent 写其他 agent 的产出文件(只读)
- ❌ 把依赖 agent 的产出内容复制到 shared.md(直接读源文件)

---

## Phase 2: Task Splitting

### Optimal Granularity

| Metric | Optimal | Acceptable | Hard Limit |
|--------|---------|------------|------------|
| Code input per sub-agent | ~300 lines | ~500 lines | 800 lines total |
| Expected output | 100-200 lines | 50-250 lines | - |
| Success rate | >93% | ~80% | <50% |

### Rules

1. **Split by logical boundaries** - never cut mid-function
2. **One sub-agent = one cohesive unit**: a controller, an API handler, a group of related functions
3. **Large files (>500 lines)**: split by responsibility
4. **Each sub-agent task must specify**:
   - ✅ Absolute file path + line range
   - ✅ Shared knowledge file path (`memory/wip/{task-id}/shared.md`)
   - ✅ Output file path (`memory/wip/{task-id}/agent-{name}.md`)
   - ✅ Expected output template
5. **Vague instructions are forbidden**
6. **子进程无派发权** — task 中明确写入：「你的产出只写文件，不得 spawn 其他 agent。如需拆分，写拆分建议并标记 NEEDS_SPLIT」

### Good/Bad Fit

| Good fit | Bad fit |
|----------|---------|
| Single input → single output | Multi-source aggregation |
| Read 300 lines → write summary | Read 16 files → merge into one |
| Focused analysis | Exploratory reading |

---

## Phase 3: Execution

### Spawning

```yaml
sessions_spawn:
  label: {task-id}-{agent-name}
  lightContext: true          # ← Token 优化:不注入完整系统提示
  runTimeoutSeconds: 600      # MANDATORY
  task: |
    ## Step 0: 任务确认(必须首先执行)
    1. 读 `memory/wip/{task-id}/shared.md`,找到 Task Registry 中 `agent-{name}` 条目
    2. 确认你的任务范围、输入文件、预期产出
    3. 评估任务复杂度:
       - 如果可直接完成 → 进入 Step 1
       - 如果需要拆分(输入 >500行 或 ≥3个独立子步骤)→ 写拆分建议到输出文件,标记 `## NEEDS_SPLIT`,更新 shared.md 状态为 ⚠️

    ## Step 1: 执行
    [具体任务指令 - 文件路径 + 行号范围]

    ## Step 2: 输出与状态回写
    1. 产出写入 `memory/wip/{task-id}/agent-{name}.md`,末尾写 `## DONE`
    2. 加锁更新 shared.md 中你的状态:
       ```bash
       (
         flock -w 10 200
         awk -i inplace '/\| agent-{name} /{sub(/\| [^│]+ \|$/, "| ✅ done |")}1' memory/wip/{task-id}/shared.md
       ) 200>memory/wip/{task-id}/.shared.lock
       ```
    3. 如果执行失败,状态写 `❌ failed`,输出文件写失败原因

    ## Constraints
    - 不得 spawn 其他 agent
    - 不得修改 shared.md 中其他 agent 的条目
    - 产出文件末尾必须有 `## DONE` 或 `## NEEDS_SPLIT` 或 `## FAILED`
```

### Token Optimization Checklist

| 优化项 | 做法 | 节省 |
|--------|------|------|
| `lightContext: true` | 子 agent 不注入完整系统提示 | ~5k/agent |
| 共享知识走磁盘 | task 只写文件路径引用 | ~3-8k/agent |
| 最小化 task 描述 | 路径+行号+模板,不写自然语言解释 | ~1-2k/agent |
| 产出写磁盘 | 不通过 announce 回传大段文本 | 避免主进程上下文膨胀 |
| 后轮 agent 按需读取前轮指定产出 | 不重新注入原始代码 | 消除级联膨胀 |

### Concurrency: max 5 concurrent sub-agents

### Flat Dispatch Rules

- **同一轮内**的 agent 互相独立,可并行
- **跨轮**的 agent 有依赖关系,必须等前轮完成+验证后再派
- 后轮 agent 的 task 中**精确指定**读取哪些前轮产出文件(按需引用,不是读全部)
- 依赖图决定分轮:A⊥B → 同轮并行;C←A → C 排在 A 的下一轮
- 主进程每轮完成后报进度给用户

**示例:C 依赖 A,D 依赖 B,A⊥B**
```
第1轮(并行): A、B
第2轮(并行): C(读 agent-a.md)、D(读 agent-b.md)
```
C 和 D 虽然在第2轮,但它们之间无依赖,仍然并行。

### Main Process Role = Commander
- Dispatch → Verify → Merge → Report progress
- **Never block on long poll calls**

### Incremental Persistence (When Working Directly)

If sub-agents fail twice on same task → main process takes over:
- Read one logical unit → immediately write to notes → next unit
- **Never** "read everything then summarize"
- Hard limit: never read >400 lines without writing notes

---

## Phase 4: Verification (Critical)

### Three-Layer Defense

**Layer 1: Timeout** - every spawn has `runTimeoutSeconds`

**Layer 2: Output verification** (mandatory after completion)
```bash
wc -l memory/wip/{task-id}/agent-{name}.md   # exists and non-empty?
head -5 memory/wip/{task-id}/agent-{name}.md  # reasonable content?
grep -c "## DONE" memory/wip/{task-id}/agent-{name}.md  # completion marker?
```
- Same task fails twice → main process does it manually

**Layer 3: Fake completion detection**
- "let me", "now I'll", "next I'll", "I need to"
- "接下来我", "让我继续", "下一步", "我需要"
- These keywords → **must verify output file**, never trust return text alone

---

## Phase 5: Merging

### Default: Skeleton → Parallel Sub-Agents → Stitch

1. **Main process writes skeleton** (~100 lines): frontmatter + chapter headings + architecture overview
2. **Sub-agents write chapters in parallel**: each reads 2-3 wip notes (<1500 lines), outputs to `memory/wip/{task-id}/agent-merge-{N}.md`
3. **Main process stitches**: cat agent-merge-*.md + spot-check transitions + fix cross-references → `merged.md`

> 注意:合并阶段的子 agent 也遵循 `agent-{name}.md` 命名范式,在 Task Registry 中正常注册。

| Total notes | Strategy |
|-------------|----------|
| < 1500 lines | Main process merges directly |
| 1500-6000 lines | Skeleton + parallel chapters |
| > 6000 lines | More sub-agents (up to 5) |

---

## Phase 6: Cleanup (Mandatory)

> 不清理就不算完成。任务完成后主进程负责一键清理。

### 正常清理流程

1. **更新 `.meta.json`**: `"status": "completed"`
2. **删除 keep-alive cron**: `openclaw cron rm {task-id}-keepalive`
3. **交付保护**(防止误删最终产出):
   ```bash
   # 如果有最终产出文件,必须先复制到目标位置
   if [ -f memory/wip/{task-id}/merged.md ]; then
     cp memory/wip/{task-id}/merged.md <目标路径>
     echo "Final output delivered."
   fi
   ```
4. **一键清理整个任务目录**:
   ```bash
   rm -rf memory/wip/{task-id}/
   ```
   - 所有中间文件(shared.md、agent-*.md、.meta.json、.shared.lock、map.md 等)全部随目录清除
5. **验证**: `ls memory/wip/` - 确认任务目录已移除

**设计理由:** 所有 agent 的产出文件统一在 `memory/wip/{task-id}/` 下,不散落到其他路径,使得任务完成后只需 `rm -rf` 一个目录即可彻底清理,无遗漏风险。

### TTL 保底清理机制

在 heartbeat 中检查过期任务:

```bash
# 检查所有 wip 任务的 .meta.json
for meta in memory/wip/*/.meta.json; do
  # 读取 createdAt + ttlHours + status
  # 如果 status != "completed" 且已超过 TTL → 提醒清理
done
```

**规则:**
- `ttlHours` 默认 24h(小任务)/ 72h(大任务)
- 超过 TTL 且 status 仍为 `running` → heartbeat 提醒用户确认是否清理
- **不自动删除**(遵守"禁止自动删除"铁律),但会主动提醒
- 用户确认后,一键清理: `rm -rf memory/wip/{task-id}/`

### 并发安全

| 风险 | 防护 |
|------|------|
| 多个 agent 写同一文件 | ❌ 禁止。每个 agent 有独立输出路径 `agent-{name}.md` |
| shared.md 并发写入 | `flock` 文件锁保护,超时 10s,只写自己的状态列 |
| shared.md 读写冲突 | 读不加锁(脏读可接受),写必须加锁 |
| 任务 ID 冲突 | 使用描述性名称 + 日期后缀(如 `wcf-analysis-0509`) |
| 孤儿文件(agent 超时未产出)| 主进程验证后加锁标记 `❌ failed`,清理阶段统一处理 |
| 锁死锁 | flock 超时 10s 自动失败,agent 写入失败不影响产出文件 |

---

## Anti-Patterns

| Anti-pattern | Correct approach |
|-------------|-----------------|
| Read entire codebase then summarize | Read one unit → write → repeat |
| Single sub-agent for 3000+ lines | Split into 5-10 at ~300 lines each |
| Main process blocks on poll(300s) | Use sessions_spawn, push-based completion |
| Trust sub-agent "completed" status | Always verify output file |
| Skip reconnaissance | Main process builds map first |
| Merge 16 files in one sub-agent | Skeleton + parallel chapters |
| Skip keep-alive cron | Always create as first action |
| Mechanical line-number splitting | Split by logical boundaries |
| **Nested sub-agents** | **子进程无派发权，回报拆分建议由主进程重新调度** |
| **Copy shared context into task text** | **Reference shared.md file path** |
| **Skip .meta.json** | **Always create for TTL tracking** |
| **Same output path for multiple agents** | **Each agent gets unique output file** |
| **子 agent 不确认任务直接开干** | **Step 0 必须先读 registry 确认任务** |
| **子 agent 执行完不回写状态** | **退出前必须加锁更新 shared.md 状态** |
| **主进程不注册就派 agent** | **派发前必须先在 registry 注册条目** |
| **在 shared.md 写背景知识/代码片段** | **shared.md 只放任务上下文+注册表** |
| **子 agent 写其他 agent 的产出文件** | **只写自己的输出文件,读其他的** |
| **产出文件散落在任务目录外** | **所有文件统一在 `memory/wip/{task-id}/` 下** |
| **任务完成后不清理或只删部分文件** | **`rm -rf memory/wip/{task-id}/` 一键清理整个目录** |

---

## Quick Reference: Spawn Template

```
sessions_spawn:
  label: {task-id}-{agent-name}
  lightContext: true
  runTimeoutSeconds: 600
  task: |
    ## Step 0: 任务确认
    读 `memory/wip/{task-id}/shared.md`,在 Task Registry 找到 `agent-{name}` 条目。
    确认任务范围、预期产出和依赖关系。评估复杂度:
    - 可直接完成 → 执行 Step 1
    - 需拆分 → 写拆分建议,标记 NEEDS_SPLIT,更新状态后退出

    如果 Depends 列标注了依赖其他 agent(如 agent-a, agent-b),
    先读取对应产出文件(如 `memory/wip/{task-id}/agent-a.md`)获取所需知识。

    ## Step 1: 执行
    分析 `{absolute-file-path}` 第 {start}-{end} 行。
    [具体分析要求]

    ## Step 2: 输出与回写
    产出写入 `memory/wip/{task-id}/agent-{name}.md`,格式:
      ## {Module Name}
      - Responsibility: one sentence
      - Key types/structs: list
      - Core flow: numbered steps
      - Dependencies: list
      - Notable decisions: bullet points
      ## DONE

    加锁更新 shared.md 状态:
    ```bash
    (
      flock -w 10 200
      awk -i inplace '/\| agent-{name} /{sub(/\| [^│]+ \|$/, "| ✅ done |")}1' memory/wip/{task-id}/shared.md
    ) 200>memory/wip/{task-id}/.shared.lock
    ```

    ## Constraints
    - 不得 spawn 其他 agent
    - 只能修改 shared.md 中自己的状态列
    - 只能写自己的输出文件 `agent-{name}.md`,其他 agent 文件只读
    - 产出文件末尾必须有 `## DONE` / `## NEEDS_SPLIT` / `## FAILED`
```

---

## Compaction Recovery

1. Read `memory/wip/{task-id}/` - check each `agent-*.md` for `## DONE`
2. Resume from where last verified, don't restart completed parts
3. `.meta.json` records overall status for quick resume判断

---

## Token Budget Reference

| 场景 | 无优化 | 优化后 | 节省 |
|------|--------|--------|------|
| 5 agent 各需完整上下文 | ~75k input | ~25k input | 67% |
| 后轮 agent 需要前轮数据 | 全部重新注入 ~30k | 读产出文件 ~5k | 83% |
| 主进程合并阶段 | 所有 agent 结果在内存 | 读磁盘文件,按需加载 | 弹性 |

**核心公式:** `子agent输入 ≈ shared.md(100行) + 目标代码(≤300行) + task指令(≤30行)`
