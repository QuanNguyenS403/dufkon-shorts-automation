$ErrorActionPreference = "Stop"

# Registers Windows Task Scheduler job to run Dufkon Shorts Producer silently (on logon + every 2h)
$TaskName = "DufkonShortsContinuousProducer"
$PythonwExe = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $PythonwExe) { $PythonwExe = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $PythonwExe) { $PythonwExe = "pythonw.exe" }

$CurrentUser = "$env:USERDOMAIN\$env:USERNAME"

$Action = New-ScheduledTaskAction `
    -Execute $PythonwExe `
    -Argument "d:\Youtube\scripts\continuous_producer.py --target-buffer-days 14 --batch-limit 3" `
    -WorkingDirectory "d:\Youtube"

$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$TriggerLogon.Delay = "PT45S"

$TriggerRepeat = New-ScheduledTaskTrigger -Once -At "00:00" -RepetitionInterval (New-TimeSpan -Hours 2)

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger @($TriggerLogon, $TriggerRepeat) `
    -Settings $Settings `
    -User $CurrentUser `
    -Force | Out-Null

Write-Host "✅ Registered silent Windows Scheduled Task: $TaskName (AtLogOn + Every 2h, Hidden pythonw, 14-day buffer)" -ForegroundColor Green
