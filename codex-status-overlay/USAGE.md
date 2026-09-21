# Codex Status Overlay

双击 `Start-CodexStatusOverlay.cmd` 启动右下角悬浮面板，点击面板右上角的 `×` 退出。

已启用随 Codex 自动启动：Windows 登录后由任务计划程序托管独立的 `CodexStatusWatcher.exe`，并在它异常退出时自动重启；注册表登录启动项作为后备。它只在检测到 Codex 真实可见、未被系统隐藏的主窗口时显示悬浮窗；关闭 Codex 窗口后，即使 Chromium 后台进程仍存在，也会关闭悬浮窗。用户手动关闭面板后，本次 Codex 窗口会话内不会再次弹出；重新打开 Codex 窗口后恢复自动显示。`Install-Autostart.ps1` 可重新安装该设置，`Remove-Autostart.ps1` 可完整取消；运行记录保存在 `watcher.log`。

将面板拖到屏幕左侧或右侧 32 像素范围内即可停靠。靠边时绿色提示条不会提前出现；鼠标移开 650 毫秒后，面板会带过渡动画收入屏幕边缘并固定保留 32 像素。动画完成后，这 32 像素区域只绘制当前上下文占用比例对应的绿色进度条，不保留面板背景或其他内容；将鼠标移到该区域会带动画完整展开。把面板拖离边缘即可取消自动隐藏。

面板每 2 秒只读检查 Codex 本地状态：

- 当前任务优先通过 Codex 桌面日志中的 `thread_stream_view_activity_changed active=true` 事件识别，并按任务 ID 映射到 `state_5.sqlite`；旧版客户端缺少该事件时再尝试窗口可访问性标题；
- 用户点击不同对话后通常会在 2 秒内自动切换；两种当前任务信号均不可用时，才回退到最近活跃的普通用户任务；
- 上下文占用来自该任务最新的 `token_count.info.last_token_usage`；
- 上限来自同一事件的 `model_context_window`；
- 5 小时与一周限额是账户级数据，始终来自所有普通任务中时间最新且包含限额的 `token_count.rate_limits`；切换到旧对话时不会回退到该对话最后活动时的旧限额。

它不会读取或展示消息正文，也不会修改 Codex 数据。任务切换通常会在 2 秒内反映；新任务需要至少完成一次模型响应后才会出现上下文和限额数据。

界面由 Codex 自带的 PowerShell 7 加载；状态读取器使用 ASCII 安全的 JSON Unicode 转义跨进程传递中文，避免 Windows 代码页将任务标题及下方信息转成乱码。当前任务标题优先使用 Codex 窗口的可访问性标题，损坏的旧数据库标题会显示为“未命名任务”。
