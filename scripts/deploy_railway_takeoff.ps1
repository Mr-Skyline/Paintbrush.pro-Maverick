Param(
  [Parameter(Mandatory = $false)]
  [string]$RailwayToken = $env:RAILWAY_TOKEN
)

if ([string]::IsNullOrWhiteSpace($RailwayToken)) {
  Write-Error "RAILWAY_TOKEN is required. Set env var or pass -RailwayToken."
  exit 1
}

$root = Split-Path -Parent $PSScriptRoot
$serviceDir = Join-Path $root "takeoff_agent"

Push-Location $serviceDir
try {
  npx @railway/cli login --token $RailwayToken
  if ($LASTEXITCODE -ne 0) { throw "Railway login failed." }

  npx @railway/cli up --detach
  if ($LASTEXITCODE -ne 0) { throw "Railway deploy failed." }

  npx @railway/cli domain
  if ($LASTEXITCODE -ne 0) { throw "Could not read Railway domain." }
}
finally {
  Pop-Location
}
