param(
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 3000,
  [switch]$KillByPort
)

$ErrorActionPreference = "Continue"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RunlogsDir = Join-Path $Root ".runlogs"
$BackendPidFile = Join-Path $RunlogsDir "backend.pid"
$FrontendPidFile = Join-Path $RunlogsDir "frontend.pid"
$PortsFile = Join-Path $RunlogsDir "dev.ports"

function Stop-ByPidFile($PidFile, $Label) {
  if (-not (Test-Path $PidFile)) {
    Write-Host "$Label PID file not found: $PidFile"
    return
  }

  $pidText = (Get-Content -Path $PidFile -Raw).Trim()
  if (-not $pidText) {
    Write-Host "$Label PID file is empty: $PidFile"
    return
  }

  try {
    $targetPid = [int]$pidText
  } catch {
    Write-Warning "$Label PID file content is invalid: $pidText"
    return
  }

  try {
    Stop-Process -Id $targetPid -Force -ErrorAction Stop
    Write-Host "Stopped $Label process PID $targetPid"
  } catch {
    Write-Host "$Label process PID $targetPid is not running."
  }
}

Stop-ByPidFile -PidFile $BackendPidFile -Label "Backend"
Stop-ByPidFile -PidFile $FrontendPidFile -Label "Frontend"

if ($KillByPort) {
  if (Test-Path $PortsFile) {
    $raw = Get-Content -Path $PortsFile -ErrorAction SilentlyContinue
    foreach ($line in $raw) {
      if ($line -match "^backend=(\d+)$") {
        $BackendPort = [int]$Matches[1]
      } elseif ($line -match "^frontend=(\d+)$") {
        $FrontendPort = [int]$Matches[1]
      }
    }
  }

  function Stop-PortOwners([int]$Port) {
    $owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerPid in $owners) {
      try {
        Stop-Process -Id $ownerPid -Force -ErrorAction Stop
        Write-Host "Stopped process PID $ownerPid on port $Port"
      } catch {
        Write-Warning "Failed to stop PID $ownerPid on port $Port"
      }
    }
  }

  Stop-PortOwners -Port $BackendPort
  Stop-PortOwners -Port $FrontendPort
}
