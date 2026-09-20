@echo off
set "CODEX_OVERLAY_PWSH=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe"
if exist "%CODEX_OVERLAY_PWSH%" (
  start "Codex Status Overlay" "%CODEX_OVERLAY_PWSH%" -NoProfile -STA -WindowStyle Hidden -File "%~dp0CodexStatusOverlay.ps1"
) else (
  echo Codex bundled PowerShell 7 was not found.
  pause
  exit /b 1
)
