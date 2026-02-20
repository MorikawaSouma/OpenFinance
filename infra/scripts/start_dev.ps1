param(
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 3000,
  [switch]$Restart
)

$ErrorActionPreference = "Stop"

function Test-Command($Name) {
  return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PortOwners([int]$Port) {
  $rows = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if (-not $rows) { return @() }
  return ($rows | Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique)
}

function Stop-PortOwners([int]$Port) {
  $owners = Get-PortOwners -Port $Port
  foreach ($ownerPid in $owners) {
    try {
      Stop-Process -Id $ownerPid -Force -ErrorAction Stop
      Write-Host "Stopped process $ownerPid on port $Port"
    } catch {
      Write-Warning "Failed to stop process $ownerPid on port $Port"
    }
  }
}

function Resolve-FreePort([int]$PreferredPort, [int[]]$Fallbacks) {
  $candidates = @($PreferredPort) + $Fallbacks
  foreach ($candidate in $candidates) {
    $owners = Get-PortOwners -Port $candidate
    if ($owners.Count -eq 0) {
      return $candidate
    }
  }
  throw "No free port found in candidates: $($candidates -join ', ')"
}

function Wait-PortOwner([int]$Port, [int]$TimeoutSec = 20) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $owners = Get-PortOwners -Port $Port
    if ($owners.Count -gt 0) {
      return $owners[0]
    }
    Start-Sleep -Milliseconds 300
  }
  return $null
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$RunlogsDir = Join-Path $Root ".runlogs"
if (-not (Test-Path $RunlogsDir)) {
  New-Item -Path $RunlogsDir -ItemType Directory | Out-Null
}

$BackendLog = Join-Path $RunlogsDir "backend.out.log"
$BackendErr = Join-Path $RunlogsDir "backend.err.log"
$FrontendLog = Join-Path $RunlogsDir "frontend.out.log"
$FrontendErr = Join-Path $RunlogsDir "frontend.err.log"
$BackendPidFile = Join-Path $RunlogsDir "backend.pid"
$FrontendPidFile = Join-Path $RunlogsDir "frontend.pid"
$PortsFile = Join-Path $RunlogsDir "dev.ports"

if (-not (Test-Command "python")) {
  throw "python not found in PATH."
}
if (-not (Test-Command "npm.cmd")) {
  throw "npm.cmd not found in PATH."
}

$backendOwners = Get-PortOwners -Port $BackendPort
$frontendOwners = Get-PortOwners -Port $FrontendPort

if (($backendOwners.Count -gt 0 -or $frontendOwners.Count -gt 0) -and -not $Restart) {
  if ($backendOwners.Count -gt 0) {
    Write-Host "Backend port $BackendPort already in use by PID(s): $($backendOwners -join ', ')"
  }
  if ($frontendOwners.Count -gt 0) {
    Write-Host "Frontend port $FrontendPort already in use by PID(s): $($frontendOwners -join ', ')"
  }
  Write-Host "Use -Restart to auto-stop existing processes and restart."
  exit 1
}

if ($Restart) {
  Stop-PortOwners -Port $BackendPort
  Stop-PortOwners -Port $FrontendPort
  Start-Sleep -Milliseconds 500
}

$selectedBackendPort = Resolve-FreePort -PreferredPort $BackendPort -Fallbacks @(8010, 8011, 18000)
$selectedFrontendPort = Resolve-FreePort -PreferredPort $FrontendPort -Fallbacks @(3001, 3100, 3200)
if ($selectedBackendPort -ne $BackendPort) {
  Write-Warning "Backend port $BackendPort unavailable, fallback to $selectedBackendPort"
}
if ($selectedFrontendPort -ne $FrontendPort) {
  Write-Warning "Frontend port $FrontendPort unavailable, fallback to $selectedFrontendPort"
}

$backendUrl = "http://127.0.0.1:$selectedBackendPort"

$backendArgs = @(
  "-m", "uvicorn", "openfinance.api.main:app",
  "--host", "0.0.0.0",
  "--port", "$selectedBackendPort"
)

$backendProc = Start-Process `
  -FilePath "python" `
  -ArgumentList $backendArgs `
  -WorkingDirectory $BackendDir `
  -RedirectStandardOutput $BackendLog `
  -RedirectStandardError $BackendErr `
  -PassThru

$oldApiBase = $env:NEXT_PUBLIC_API_BASE
$env:NEXT_PUBLIC_API_BASE = $backendUrl
$frontendProc = Start-Process `
  -FilePath "npm.cmd" `
  -ArgumentList "run", "dev", "--", "--port", "$selectedFrontendPort" `
  -WorkingDirectory $FrontendDir `
  -RedirectStandardOutput $FrontendLog `
  -RedirectStandardError $FrontendErr `
  -PassThru
if ($null -eq $oldApiBase) {
  Remove-Item Env:\NEXT_PUBLIC_API_BASE -ErrorAction SilentlyContinue
} else {
  $env:NEXT_PUBLIC_API_BASE = $oldApiBase
}

$backendOwnerPid = Wait-PortOwner -Port $selectedBackendPort -TimeoutSec 12
$frontendOwnerPid = Wait-PortOwner -Port $selectedFrontendPort -TimeoutSec 20

if ($null -eq $backendOwnerPid) { $backendOwnerPid = $backendProc.Id }
if ($null -eq $frontendOwnerPid) { $frontendOwnerPid = $frontendProc.Id }

Set-Content -Path $BackendPidFile -Value "$backendOwnerPid" -Encoding ascii
Set-Content -Path $FrontendPidFile -Value "$frontendOwnerPid" -Encoding ascii
Set-Content -Path $PortsFile -Value "backend=$selectedBackendPort`nfrontend=$selectedFrontendPort" -Encoding ascii

Write-Host "OpenFinance dev services started."
Write-Host "Backend:  $backendUrl/docs (PID $backendOwnerPid)"
Write-Host "Frontend: http://127.0.0.1:$selectedFrontendPort (PID $frontendOwnerPid)"
Write-Host "Logs:"
Write-Host "  $BackendLog"
Write-Host "  $FrontendLog"
Write-Host "Ports file: $PortsFile"
Write-Host "Stop with: powershell -ExecutionPolicy Bypass -File infra/scripts/stop_dev.ps1"
