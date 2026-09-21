$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$watcherPath = Join-Path $scriptRoot 'CodexStatusWatcher.exe'
$providerPath = Join-Path $scriptRoot 'read_status.py'

if (-not (Test-Path -LiteralPath $watcherPath)) {
    throw '未找到 Codex 状态悬浮窗 EXE 监视器。'
}

$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pythonPath = if (Test-Path -LiteralPath $bundledPython) {
    $bundledPython
} elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
    (Get-Command py.exe).Source
} elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
    (Get-Command python.exe).Source
} else {
    throw '未找到 Python，无法初始化历史用量记录。'
}

# Create the installation baseline before the watcher starts. Existing rollout
# bytes are checkpointed but never counted, so history begins at installation.
$historyResult = & $pythonPath $providerPath --initialize-history | ConvertFrom-Json
if (-not $historyResult.ok) {
    throw ([string]$historyResult.error)
}

# The original PowerShell scheduled task could be terminated with 0xC000013A.
# The watcher is now a compiled EXE, so let Task Scheduler own that process and
# restart it if it exits unexpectedly. Keep the Run entry as a login fallback;
# the watcher's named mutex makes duplicate launches harmless.
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

$taskInstalled = $false
try {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $watcherPath -WorkingDirectory $scriptRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -StartWhenAvailable
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings
    Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    $taskInstalled = $true
}
catch {
    Write-Warning ('无法注册任务计划程序，已保留注册表登录启动作为后备：' + $_.Exception.Message)
    Start-Process -FilePath $watcherPath -WindowStyle Hidden
}

if ($taskInstalled) {
    $historyTime = [DateTimeOffset]::FromUnixTimeSeconds([int64]$historyResult.installed_at).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss')
    Write-Output ('Codex 状态悬浮窗已注册为登录启动；历史用量从 ' + $historyTime + ' 开始记录。')
}
