# C:\watchdog\setup.ps1
# 注册 GlobalWatchdog Task Scheduler 任务（每5分钟）
# 以管理员身份运行：
#   powershell -ExecutionPolicy Bypass -File "C:\watchdog\setup.ps1"

$python = 'C:\Python314\pythonw.exe'

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "C:\watchdog\watchdog.py" `
    -WorkingDirectory "C:\watchdog"

$trigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 9999)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName 'GlobalWatchdog' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Description 'Global process watchdog — checks all registered persistent processes every 5 min' `
    -Force | Out-Null

Write-Host "OK: GlobalWatchdog registered (every 5 min, RunLevel=Highest)"
Write-Host "Verify in Task Scheduler under: Task Scheduler Library > GlobalWatchdog"
