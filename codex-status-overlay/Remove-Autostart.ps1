$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runName = 'CodexStatusOverlayWatcher'
Remove-ItemProperty -Path $runKey -Name $runName -ErrorAction SilentlyContinue
$taskName = 'CodexStatusOverlayWatcher'
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Get-Process -Name 'CodexStatusWatcher' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$overlayPath = Join-Path $scriptRoot 'CodexStatusOverlay.ps1'
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -in @('pwsh.exe', 'powershell.exe') -and $_.CommandLine -like ('*' + $overlayPath + '*')
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Output '已取消 Codex 状态悬浮窗自动启动。'
