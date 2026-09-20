---
name: codex-status-panel
description: Display the current Codex five-hour and weekly usage limits together with a grounded summary of the active conversation context. Use when the user asks for Codex quota, remaining usage, reset times, status, or the context of the currently open task.
---

# Codex 状态面板

生成一个简洁的中文状态面板，同时覆盖账号限额和当前打开任务的上下文。

## 数据获取

- 调用 Codex 原生的账号用量读取能力获取最新限额。不要从旧消息、缓存、账户套餐名称或经验值推算。
- 优先读取 `rateLimitsByLimitId.codex`；若缺失，再读取兼容字段 `rateLimits`。
- 用 `windowDurationMins` 识别窗口：`300` 是 5 小时窗口，`10080` 是一周窗口。不要假设 `primary` 和 `secondary` 永远对应固定窗口。
- `usedPercent` 表示已用比例；剩余比例按 `max(0, 100 - usedPercent)` 计算。缺失值显示“不可用”，不要当作 0。
- 将 `resetsAt` Unix 秒时间戳转换为用户本地时区的绝对日期和时间，并附相对剩余时间。
- 不显示账户 ID、内部原始响应或其他与面板无关的账户信息。

## 当前任务上下文

只根据当前任务中模型真实可见的信息，归纳：

- 任务标题（可见时）和工作目录/项目；
- 用户当前目标与最近一次请求；
- 已确认的重要约束或决策；
- 正在进行的工作、待办或阻塞项。

不要把屏幕上其他应用、未加载的旧消息或隐藏系统状态描述为已知事实。普通文本对话中不要调用仅限实时语音会话的屏幕上下文能力。如果精确 token 上下文占用或最大上下文长度没有可靠来源，显示“当前不可用”，不要估算。

## 输出格式

以“Codex 状态”为标题，使用两个小节：

1. “限额”——用紧凑表格列出窗口、已用、剩余、重置时间和状态。
2. “当前任务上下文”——用不超过五条短项目符号概括上下文；无待办时明确写“无”。

当限额读取失败时，仍然显示上下文部分，并在限额部分给出简短、可操作的失败说明。除非用户明确要求，不要输出冗长解释。
