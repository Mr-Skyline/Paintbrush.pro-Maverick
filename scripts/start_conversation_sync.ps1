param(
  [string]$TranscriptPath = "",
  [switch]$NoAutoPush
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$defaultTranscript = "C:\Users\travi\.cursor\projects\c-Users-travi-OneDrive-Documents-Paintbrush-pro\agent-transcripts\e67a9fa2-082b-4d47-ad1a-6e3f14337db6\e67a9fa2-082b-4d47-ad1a-6e3f14337db6.jsonl"

if ([string]::IsNullOrWhiteSpace($TranscriptPath)) {
  $TranscriptPath = $defaultTranscript
}

$autoPushArg = ""
if (-not $NoAutoPush) {
  $autoPushArg = "--auto-push"
}

Write-Output "conversation_sync_start transcript=$TranscriptPath auto_push=$(-not $NoAutoPush)"
python "$PSScriptRoot\conversation_github_sync.py" `
  --repo-root "$repoRoot" `
  --transcript "$TranscriptPath" `
  --watch `
  --interval-s 2 `
  $autoPushArg

