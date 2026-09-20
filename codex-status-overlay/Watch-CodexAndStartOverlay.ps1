# Compatibility launcher retained for older shortcuts. The long-running
# PowerShell watcher was replaced because Windows could terminate it with
# 0xC000013A. Autostart is now owned by CodexStatusWatcher.exe.
$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$watcherPath = Join-Path $scriptRoot 'CodexStatusWatcher.exe'
if (-not (Test-Path -LiteralPath $watcherPath)) {
    throw '未找到 CodexStatusWatcher.exe。请重新运行 Install-Autostart.ps1。'
}
Start-Process -FilePath $watcherPath -WindowStyle Hidden
