---
name: self-review
description: "Periodic self-review and improvement tracking. Triggers on: (1) daily evening heartbeat — log today's learnings and metrics, (2) weekly Sunday heartbeat — summarize weekly trends, (3) monthly 1st heartbeat — generate monthly report with feedback to user. Also triggers when user asks to review/evaluate training progress, improvement data, or correction history."
---

# Self-Review Skill

Structured self-improvement tracking with periodic reviews and data-driven feedback.

## Overview

Records corrections, errors, and learnings during daily work. Periodically reviews and summarizes data to identify patterns, track improvement, and provide actionable feedback to the user.

## Data Structure

```
.learnings/
├── LEARNINGS.md           # Corrections, insights, best practices
├── ERRORS.md              # Technical errors and failures
├── FEATURE_REQUESTS.md    # Missing capabilities
└── metrics/
    ├── schema.json        # Metric definitions
    ├── YYYY-MM-DD.json    # Daily metrics
    ├── week-YYYY-WXX.json # Weekly summaries
    └── month-YYYY-MM.json # Monthly summaries
```

## Metrics Tracked

| Metric | Description |
|--------|-------------|
| `corrections` | Times corrected by user |
| `instant_fix_rate` | Fixed correctly on first attempt |
| `repeat_error_rate` | Same error type recurring |
| `proactive_learnings` | Self-initiated recordings (not prompted) |
| `errors_logged` | Technical errors documented |
| `rules_added` | New behavior rules established |
| `feedback_to_user` | Suggestions offered to user |
| `tokens_in` | Input tokens consumed |
| `tokens_out` | Output tokens generated |
| `cache_hit_rate` | Context cache hit percentage |
| `compactions` | Number of context compactions |
| `context_usage_pct` | Peak context window usage (%) |
| `effective_turns` | Turns that produced useful output (non-NO_REPLY) |
| `total_turns` | Total turns (including heartbeats, NO_REPLY) |
| `turn_efficiency` | effective_turns / total_turns |

## Trigger: Real-Time Recording

**When to record (during any conversation):**

| Event | Action | File |
|-------|--------|------|
| Command/operation fails | Log error details + root cause + fix | `.learnings/ERRORS.md` |
| User corrects me | Log as correction with context | `.learnings/LEARNINGS.md` |
| User questions my approach | Log as learning signal (even if I think I'm right) | `.learnings/LEARNINGS.md` |
| Discover better method | Log as best_practice | `.learnings/LEARNINGS.md` |
| User wants capability I lack | Log feature request | `.learnings/FEATURE_REQUESTS.md` |

**Recording threshold is LOW**: if there's discussion value, record it.

## Trigger: Daily Review (Evening Heartbeat)

1. Review today's conversations for missed learnings/errors
2. Supplement `.learnings/` with anything missed
3. Write daily metrics to `.learnings/metrics/YYYY-MM-DD.json`
4. Promote significant insights to `MEMORY.md`

### Daily Metrics Template

```json
{
  "date": "YYYY-MM-DD",
  "corrections": 0,
  "instant_fix_rate": 1.0,
  "repeat_error_rate": 0,
  "proactive_learnings": 0,
  "errors_logged": 0,
  "rules_added": 0,
  "feedback_to_user": 0,
  "token_usage": {
    "tokens_in": 0,
    "tokens_out": 0,
    "cache_hit_rate": 0,
    "compactions": 0,
    "context_usage_pct": 0
  },
  "efficiency": {
    "effective_turns": 0,
    "total_turns": 0,
    "turn_efficiency": 0,
    "avg_tokens_per_effective_turn": 0
  },
  "highlights": [],
  "correction_details": [],
  "token_notes": ""
}
```

## Trigger: Weekly Review (Sunday Heartbeat)

1. Read all daily metrics for the week
2. Calculate weekly aggregates and trends
3. Write `.learnings/metrics/week-YYYY-WXX.json`
4. Identify recurring patterns → promote to `AGENTS.md` or `TOOLS.md`
5. Compare with previous weeks: is correction rate declining? Is proactive recording increasing?

### Weekly Summary Template

```json
{
  "week": "YYYY-WXX",
  "period": "YYYY-MM-DD to YYYY-MM-DD",
  "total_corrections": 0,
  "avg_instant_fix_rate": 0,
  "repeat_errors": [],
  "top_learnings": [],
  "patterns_promoted": [],
  "trend": "improving | stable | declining"
}
```

## Trigger: Monthly Review (1st of Month Heartbeat)

1. Aggregate all weekly summaries for the month
2. Write `.learnings/metrics/month-YYYY-MM.json`
3. Generate feedback report for user (if applicable)
4. Feedback format: `现象 → 建议 → 预期效果` (observation → suggestion → expected outcome)

### Feedback Rules

- Only suggest when there's a clear data-backed pattern
- Tone: objective, not pushy — it's a reference, not a demand
- Examples of valid feedback:
  - "I noticed you often specify X after I ask — could include it upfront to save a round-trip"
  - "Pattern: corrections cluster around topic Y — I may need a clearer rule for this area"

## Data Retention

| Level | Retention | Cleanup |
|-------|-----------|---------|
| Daily metrics | 30 days | Auto-clean, no approval needed |
| Weekly summaries | 6 months | Auto-clean, no approval needed |
| Monthly summaries | Permanent | Never auto-delete |
| LEARNINGS.md | Permanent | Never auto-delete |
| ERRORS.md | Permanent | Never auto-delete |

**Cleanup runs during monthly review**: delete expired daily/weekly files automatically.

## Hard Constraints

- ✅ Auto-add content (record, summarize, promote)
- ❌ **Never auto-delete LEARNINGS.md, ERRORS.md, or FEATURE_REQUESTS.md content**
- ❌ Never delete monthly summaries
- ✅ Auto-delete expired daily/weekly metric files (within retention policy)
- ❌ Never fabricate metrics — if data is missing, mark as `null`

## Token Usage Tracking

### Data Source

Run `session_status` (or `/status`) to get current session token stats:
- `tokens_in` / `tokens_out`
- `cache_hit_rate`
- `context_usage_pct`
- `compactions`

### What to Track

| Metric | 意义 | 优化方向 |
|--------|------|----------|
| tokens_in + tokens_out | 总消耗 | 减少冗余输出、避免重复读文件 |
| cache_hit_rate | 缓存命中 | 越高越省钱，稳定的 context 有助于缓存 |
| compactions | 上下文压缩次数 | 多次压缩说明对话太长，考虑拆分任务 |
| turn_efficiency | 有效转化率 | 减少无效 turn（重复确认、多余 NO_REPLY） |
| avg_tokens_per_effective_turn | 单次有效交互的平均成本 | 回复精節，避免超长输出 |

### 分析规则（周/月复盘时）

1. **token 趋势**: 每周总消耗是否稳定？有无异常峰值？
2. **浪费点识别**:
   - 重复读同一文件（应该记住内容）
   - 输出过长（应该精節）
   - 多次失败重试（应该先查原因）
   - 无效 heartbeat（没产生价值的唤醒）
3. **优化建议**: 归纳后写入月度报告，反馈给用户

### 常见优化手段

| 问题 | 优化 |
|------|------|
| 回复啰嘆、重复确认 | 精節输出，一次说清 |
| 多次 read 同一文件 | 记住内容，避免重复读 |
| 工具调用失败重试 | 先查文档/原因，再执行 |
| 无效 heartbeat | 减少频率或精简检查项 |
| context 爆满压缩 | 拆分为多个短会话 / 用 sub-agent |
