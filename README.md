# openclaw-skill

OpenClaw 自定义技能仓库 —— 黄金藤椒大鸡腿的完整技能集合与设计文档。

## 技能列表

| Skill | 用途 | 来源 |
|-------|------|------|
| `news-scout` | 美股 + AI 全球/国内新闻聚合（39 RSS 源） | 自建 |
| `news-aggregator-skill` | 华尔街见闻、36Kr 等国内财经深度分析 | 自建 |
| `stock-trader` | A 股实时行情 + 消息面分析 + 模拟交易 | 自建 |
| `todo` | 本地持久化待办管理（自然语言 → 结构化行动） | 自建 |
| `caldav-calendar` | iCloud 日历（CalDAV，vdirsyncer + khal） | 自建 |
| `porteden-email` | 邮箱管理（只读） | clawhub |
| `self-review` | 定时复盘（日/周/月），指标跟踪 | 自建 |
| `large-task-strategy` | 多 agent 编排设计 | 自建 ★ |
| `self-improving-agent` | 自动记录错误/纠正/经验 | skillhub |
| `proactive-agent` | 主动性架构（WAL、Working Buffer） | skillhub |
| `coding-guidelines` | AI 编码最佳实践 | 自建 |
| `debugger` | 调试协议（Node.js/Python/Go/Bash） | 第三方 |
| `agent-browser-clawdbot` | 无头浏览器自动化 | 第三方 |
| `github` | GitHub CLI 交互 | 第三方 |
| `memory-hygiene` | LanceDB 向量记忆清理 | 第三方 |
| `openclaw-tavily-search` | Tavily Web 搜索 | 第三方 |
| `web-tools-guide` | Web 工具选择策略 | 自建 |
| `find-skills` | 技能发现流程 | 自建 |
| `skillhub-preference` | skillhub 优先策略 | 自建 |
| `tencentcloud-lighthouse-skill` | 腾讯云轻量服务器管理 | 第三方 |
| `weather` | 天气查询 | skillhub |

> ★ 带 `docs/` 目录下 design 文档的为深度定制技能，包含完整设计思路和架构决策。

## 目录结构

```
skills/
├── <skill-name>/
│   ├── SKILL.md           # 技能入口（必须）
│   ├── design.md          # 设计文档（深度定制技能）
│   ├── scripts/           # 可执行脚本
│   ├── references/        # 参考资料
│   └── resources/         # 配置/数据文件
docs/                      # 跨技能设计文档（待补充）
```

## 约定

- 每个技能遵循 [AgentSkills 规范](https://docs.openclaw.ai/skills)
- **有 `design.md` 的技能 = 深度定制**：包含设计动机、架构模型、协议定义等
- 不含任何 token / API key / 隐私数据

## 维护

- 维护者：[@ReadyDog](https://github.com/ReadyDog)
- 所有者：[@NorthCedar](https://github.com/NorthCedar)
