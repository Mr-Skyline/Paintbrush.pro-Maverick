param(
  [string]$ShortcutName = "Paintbrush Maverick Runtime.lnk"
)

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup $ShortcutName
if (Test-Path $shortcutPath) {
  Remove-Item $shortcutPath -Force
  Write-Host "Removed startup shortcut: $shortcutPath"
} else {
  Write-Host "Startup shortcut not found: $shortcutPath"
}
