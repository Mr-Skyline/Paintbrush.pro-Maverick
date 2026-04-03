param(
  [string]$TaskName = "PaintbrushMaverickRuntime"
)

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Removed scheduled task (if it existed): $TaskName"
