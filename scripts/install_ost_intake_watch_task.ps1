param(
  [string]$TaskName = "PaintbrushMaverickRuntime",
  [string]$Workspace = "C:\Users\travi\OneDrive\Documents\Paintbrush.pro",
  [string]$PythonExe = "python",
  [string]$IntakeConfig = "scripts\ost_project_intake.config.json",
  [string]$MaverickConfig = "scripts\maverick_runtime.config.json",
  [ValidateSet("maverick-always-on", "intake-watch")]
  [string]$Mode = "maverick-always-on",
  [switch]$RunHighest
)

$scriptPath = Join-Path $Workspace "scripts\ost_orchestrator.py"
if ($Mode -eq "intake-watch") {
  $actionArgs = "`"$scriptPath`" intake-watch --intake-config `"$IntakeConfig`""
} else {
  $actionArgs = "`"$scriptPath`" maverick-always-on --config `"$MaverickConfig`""
}

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $actionArgs -WorkingDirectory $Workspace
$trigger = New-ScheduledTaskTrigger -AtLogOn
$runLevel = "Limited"
if ($RunHighest) {
  $runLevel = "Highest"
}
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel $runLevel
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0)

try {
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force -ErrorAction Stop
  Write-Host "Installed scheduled task: $TaskName (RunLevel=$runLevel)"
} catch {
  Write-Error "Failed to install scheduled task '$TaskName': $($_.Exception.Message)"
  exit 1
}
