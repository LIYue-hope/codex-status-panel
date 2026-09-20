$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$watcherPath = Join-Path $scriptRoot 'CodexStatusWatcher.exe'

if (-not (Test-Path -LiteralPath $watcherPath)) {
    throw '未找到 Codex 状态悬浮窗 EXE 监视器。'
}

# Remove the scheduled-task implementation that Windows was terminating with
# 0xC000013A, then let Explorer launch the independent watcher at each login.
$taskName = 'CodexStatusOverlayWatcher'
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Stop only previous instances belonging to this overlay installation.
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.ExecutablePath -eq $watcherPath) -or
    ($_.Name -in @('pwsh.exe', 'powershell.exe') -and
        ($_.CommandLine -like ('*' + (Join-Path $scriptRoot 'Watch-CodexAndStartOverlay.ps1') + '*') -or
         $_.CommandLine -like ('*' + (Join-Path $scriptRoot 'CodexStatusOverlay.ps1') + '*')))
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runName = 'CodexStatusOverlayWatcher'
if (-not (Test-Path -LiteralPath $runKey)) { New-Item -Path $runKey -Force | Out-Null }
Set-ItemProperty -Path $runKey -Name $runName -Type String -Value ('"' + $watcherPath + '"')

# A startup entry disabled in Task Manager leaves a binary marker behind even
# after its Run value is replaced. Clear that stale decision so this freshly
# installed entry is eligible to run after the next sign-in.
$startupApprovalKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
Remove-ItemProperty -Path $startupApprovalKey -Name $runName -ErrorAction SilentlyContinue

Start-Process -FilePath $watcherPath -WindowStyle Hidden

Write-Output 'Codex 状态悬浮窗已注册为登录启动，并由独立 EXE 监视 Codex 可见主窗口。'
