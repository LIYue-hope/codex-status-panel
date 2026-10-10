# Codex Status Panel

为 Codex Desktop 提供两种互补的状态查看方式：对话中的状态面板插件，以及 Windows 桌面右下角悬浮窗。

## 功能

- 在 Codex 对话中显示 5 小时和一周用量窗口、已用比例、剩余比例和重置时间。
- 基于当前对话中真实可见的信息，简要总结当前任务、目录、约束、进度和待办。
- Windows 悬浮窗每两秒只读一次 Codex 本地状态，显示当前任务的上下文占用、账户级限额，以及一周限额旁的可用重置次数。
- 对话名称右侧显示实时输出速度 `≈ xx.x token/s`，字体与下方模型名称一致；每 0.5 秒更新近 5 秒可见文本的流式速度。
- 悬浮窗标题栏新增“历史用量”，可按自定义日期范围查看安装后的总 Token、输入、缓存输入、输出和推理输出。
- 历史统计从运行悬浮窗安装脚本（或首次启动悬浮窗）时开始，不会追溯计入安装前的会话。
- 悬浮窗可拖拽、贴靠屏幕左右边缘，并在鼠标离开后自动收起为进度条。
- 可随 Windows/Codex 自动启动；关闭 Codex 主窗口时悬浮窗会退出。
- 测速只在内存中处理当前对话的输出文本，不展示、保存或上传正文，也不修改 Codex 数据。

## 要求

- Codex Desktop（用于状态面板插件）。
- Windows 与 Codex 自带的 PowerShell 7（用于桌面悬浮窗）。
- Codex 自带的 Python 3，以及 `tiktoken` 依赖（用于流式测速）。
- 上下文占用和本地限额需要当前任务至少完成过一次模型响应；流式测速需要可用的桌面 IPC 通道。

## 安装 Codex 插件

### 从 GitHub 安装

在 PowerShell 中运行：

```powershell
codex plugin marketplace add LIYue-hope/codex-status-panel
codex plugin add codex-status-panel@personal
```

安装后重启 Codex，或创建一个新任务。可以直接询问“显示当前 Codex 限额和任务上下文”。

### 从本地克隆目录安装

```powershell
git clone https://github.com/LIYue-hope/codex-status-panel.git
cd codex-status-panel
codex plugin marketplace add .
codex plugin add codex-status-panel@personal
```

若已添加同名市场或插件，请先在 Codex 中移除旧版本，再重新执行安装命令。

## 使用桌面悬浮窗

进入 `codex-status-overlay` 目录，双击：

```text
Start-CodexStatusOverlay.cmd
```

也可以在 PowerShell 中执行：

```powershell
.\Install-Autostart.ps1
```

它会配置自动启动。要取消自动启动，执行：

```powershell
.\Remove-Autostart.ps1
```

`Install-Autostart.ps1` 会同时写入历史记录基线。之后点击悬浮窗标题栏的“历史用量”，选择开始和结束日期并点击“查询”即可查看总 Token 用量；结束日期按自然日完整计入。记录数据库位于 `%LOCALAPPDATA%\CodexStatusPanel\usage-history.sqlite`，重新安装或升级不会重置已有历史。

使用时可将悬浮窗拖到屏幕左右边缘；停靠后鼠标移开约 650 毫秒，窗口会收起为一条显示上下文占用比例的绿色进度条。

## 流式输出速度

输出速度位于对话名称右侧，与下方模型名称使用相同的字体、11 号字号和颜色。悬浮窗通过 Windows `codex-ipc` 命名管道订阅当前对话的实时文本变化，每 0.5 秒刷新一次近 5 秒的输出速度。切换对话会清空采样，不会把另一段对话的速度带过来。

`≈` 表示估算值：监听器使用公开的 `o200k_base` 分词词表计算可见输出文本的 Token 数，不保证与当前模型的服务端分词完全一致。它不包含隐藏推理和工具输出，也不是整轮响应的平均速度。

| 显示 | 含义 |
| --- | --- |
| `≈ xx.x token/s` | 有文本输出时更新速度；暂停、运行命令、速度为 0 或连接异常时保留最后有效数值 |
| `≈ 0.0 token/s` | 当前对话尚无有效速度；切换对话时重置为此数值 |

首次使用时，在仓库根目录用悬浮窗使用的同一 Python 安装依赖。以下命令把依赖和下载缓存保存到项目目录；若项目位于 D 盘，两者也都保存在 D 盘：

```powershell
$overlayPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $overlayPython -m pip install tiktoken --target .\codex-status-overlay\dependencies --cache-dir .\codex-status-overlay\dependency-cache
```

仓库附带 `codex-status-overlay/tokenizer-cache` 中的公开分词词表。后台监听器仅使用本地词表，不会自动下载缺失词表。安装依赖后重新启动悬浮窗即可。连接使用桌面端内部 IPC 协议，Codex 升级导致协议变化时可能需要更新监听器。更多使用说明见 [USAGE.md](codex-status-overlay/USAGE.md)。

## 实时重置卡查询（可选）

悬浮窗的“设置”页提供“启用实时账户查询”开关，默认关闭。开启后，悬浮窗会通过 Codex 本地 app-server 的只读限额接口查询账户中的可用重置卡数量，并在“一周限额”后显示；该查询不会读取对话内容，也不会兑换或消耗重置卡。

这与其余状态信息不同：上下文、5 小时/一周限额和历史用量继续只读取本地 Codex 状态。实时查询依赖已登录的 Codex CLI 及可用的本地 app-server；成功查询的次数会保存为最近结果。关闭实时查询后仍显示该次数，再次开启时刷新；没有成功查询记录且接口不可用时，悬浮窗会明确显示“重置次数不可用”，不会将其误报为 0。

## 项目结构

```text
.agents/plugins/marketplace.json       本地/远程插件市场定义
plugins/codex-status-panel/            Codex 插件本体
codex-status-overlay/                  Windows 桌面悬浮窗及其状态读取器
codex-status-overlay/stream_speed.py   当前对话流式测速监听器
codex-status-overlay/tokenizer-cache/  本地公开分词词表
```

`watcher.log` 是运行日志，默认不提交到仓库。

## 隐私

上下文、限额和历史统计读取状态元数据（任务标识、Token 用量、上下文上限和窗口可见性）。流式测速订阅当前对话的状态快照和增量补丁，在内存中处理输出文本；消息正文不展示、不写入测速日志、不上传，监听器随悬浮窗退出。悬浮窗在本机保存自己的历史用量数据库、界面设置和运行日志，不修改 Codex 的数据库或会话文件。插件按照 Codex 可见上下文生成摘要，不应将不可见数据视为已知信息。
