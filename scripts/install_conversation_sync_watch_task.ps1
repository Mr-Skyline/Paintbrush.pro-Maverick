param(
  [string]$TaskName = "PaintbrushConversationSync",
  [string]$Workspace = "C:\Users\travi\OneDrive\Documents\Paintbrush.pro",
  [string]$PowerShellExe = "powershell.exe",
  [string]$TranscriptPath = "C:\Users\travi\.cursor\projects\c-Users-travi-OneDrive-Documents-Paintbrush-pro\agent-transcripts\e67a9fa2-082b-4d47-ad1a-6e3f14337db6\e67a9fa2-082b-4d47-ad1a-6e3f14337db6.jsonl",
  [switch]$NoAutoPush,
  [switch]$RunHighest
)

$launcherPath = Join-Path $Workspace "scripts\start_conversation_sync.ps1"
if (-not (Test-Path $launcherPath)) {
  Write-Error "Launcher not found: $launcherPath"
  exit 1
}

$argList = @(
  "-ExecutionPolicy", "Bypass",
  "-File", "`"$launcherPath`"",
  "-TranscriptPath", "`"$TranscriptPath`""
)
if ($NoAutoPush) {
  $argList += "-NoAutoPush"
}
$actionArgs = ($argList -join " ")

$action = New-ScheduledTaskAction -Execute $PowerShellExe -Argument $actionArgs -WorkingDirectory $Workspace
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
  Write-Host "Action: $PowerShellExe $actionArgs"
} catch {
  Write-Error "Failed to install scheduled task '$TaskName': $($_.Exception.Message)"
  exit 1
}

