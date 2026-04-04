Param(
  [Parameter(Mandatory = $false)]
  [string]$EnvFile = ".env.cloud"
)

$ErrorActionPreference = "Stop"

function Write-Ok($msg) { Write-Host "[OK]  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red }

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
  Write-Host "Cloud Agent preflight for Paintbrush.pro" -ForegroundColor Cyan

  $branch = git branch --show-current
  if ([string]::IsNullOrWhiteSpace($branch)) {
    Write-Fail "Not in a git repository."
    exit 1
  }
  Write-Ok "Git branch: $branch"

  $remote = git remote get-url origin 2>$null
  if ([string]::IsNullOrWhiteSpace($remote)) {
    Write-Fail "Missing git origin remote."
    exit 1
  }
  Write-Ok "Origin remote detected: $remote"

  $dirty = git status --porcelain
  if ($dirty) {
    Write-Warn "Working tree has uncommitted changes. Cloud agents can run, but commit/push is recommended first."
  } else {
    Write-Ok "Working tree clean."
  }

  if (-not (Test-Path ".cursor/environment.json")) {
    Write-Warn "Missing .cursor/environment.json"
  } else {
    Write-Ok ".cursor/environment.json found."
  }

  if (-not (Test-Path "AGENTS.md")) {
    Write-Warn "Missing AGENTS.md"
  } else {
    Write-Ok "AGENTS.md found."
  }

  if (-not (Test-Path $EnvFile)) {
    Write-Warn "$EnvFile not found. Copy from .env.cloud.template and fill keys."
  } else {
    Write-Ok "$EnvFile found."
    $required = @(
      "GROK_API_KEY",
      "TAKEOFF_CV_API_URL",
      "SUPABASE_URL",
      "SUPABASE_ANON_KEY"
    )
    $content = Get-Content $EnvFile -Raw
    foreach ($key in $required) {
      if ($content -match "(?m)^$key=(.+)$") {
        $value = $Matches[1].Trim()
        if ([string]::IsNullOrWhiteSpace($value)) {
          Write-Warn "$key is empty in $EnvFile"
        } else {
          Write-Ok "$key has a value."
        }
      } else {
        Write-Warn "$key is missing in $EnvFile"
      }
    }
  }

  Write-Host ""
  Write-Host "Preflight complete. Next:" -ForegroundColor Cyan
  Write-Host "1) Push branch to GitHub"
  Write-Host "2) Open Cursor Cloud Agents and select this branch"
  Write-Host "3) Add secrets in cloud agent settings (or provider envs)"
}
finally {
  Pop-Location
}
