param(
  [string]$Workspace = "C:\Users\travi\OneDrive\Documents\Paintbrush.pro",
  [string]$PythonExe = "python",
  [string]$IntakeConfig = "scripts\ost_project_intake.config.json",
  [string]$MaverickConfig = "scripts\maverick_runtime.config.json",
  [ValidateSet("maverick-always-on", "intake-watch")]
  [string]$Mode = "maverick-always-on",
  [string]$ShortcutName = "Paintbrush Maverick Runtime.lnk"
)

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup $ShortcutName
$scriptPath = Join-Path $Workspace "scripts\ost_orchestrator.py"
if ($Mode -eq "intake-watch") {
  $args = "`"$scriptPath`" intake-watch --intake-config `"$IntakeConfig`""
  $description = "Starts Paintbrush OST intake watcher at login"
} else {
  $args = "`"$scriptPath`" maverick-always-on --config `"$MaverickConfig`""
  $description = "Starts Paintbrush Maverick always-on runtime at login"
}

$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath = $PythonExe
$sc.Arguments = $args
$sc.WorkingDirectory = $Workspace
$sc.WindowStyle = 1
$sc.Description = $description
$sc.Save()

Write-Host "Installed startup shortcut: $shortcutPath"
