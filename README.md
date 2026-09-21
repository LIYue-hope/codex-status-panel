# Codex Status Panel

为 Codex Desktop 提供两种互补的状态查看方式：对话中的状态面板插件，以及 Windows 桌面右下角悬浮窗。

## 功能

- 在 Codex 对话中显示 5 小时和一周用量窗口、已用比例、剩余比例和重置时间。
- 基于当前对话中真实可见的信息，简要总结当前任务、目录、约束、进度和待办。
- Windows 悬浮窗每两秒只读一次 Codex 本地状态，显示当前任务的上下文占用和账户级限额。
- 悬浮窗标题栏新增“历史用量”，可按自定义日期范围查看安装后的总 Token、输入、缓存输入、输出和推理输出。
- 历史统计从运行悬浮窗安装脚本（或首次启动悬浮窗）时开始，不会追溯计入安装前的会话。
- 悬浮窗可拖拽、贴靠屏幕左右边缘，并在鼠标离开后自动收起为进度条。
- 可随 Windows/Codex 自动启动；关闭 Codex 主窗口时悬浮窗会退出。
- 不读取或展示对话正文，也不修改 Codex 数据。

## 要求

- Codex Desktop（用于状态面板插件）。
- Windows 与 Codex 自带的 PowerShell 7（用于桌面悬浮窗）。
- 若希望显示实时状态，当前任务至少需要完成过一次模型响应。

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

## 项目结构

```text
.agents/plugins/marketplace.json       本地/远程插件市场定义
plugins/codex-status-panel/            Codex 插件本体
codex-status-overlay/                  Windows 桌面悬浮窗及其状态读取器
```

`watcher.log` 是运行日志，默认不提交到仓库。

## 隐私

悬浮窗仅读取状态元数据（任务标识、Token 用量、上下文上限和窗口可见性），不读取或上传聊天消息正文。它只在本机写入自己的历史用量数据库，不修改 Codex 的数据库或会话文件。插件按照 Codex 可见上下文生成摘要，不应将不可见数据视为已知信息。
