Write-Host "Running backend acceptance checks..."

Push-Location "$PSScriptRoot\..\..\backend"
try {
  python -m pytest -q
  if ($LASTEXITCODE -ne 0) {
    throw "pytest failed"
  }

  Write-Host "Checking /healthz and /docs via TestClient..."
  @'
from fastapi.testclient import TestClient
from openfinance.api.main import app

c = TestClient(app)
assert c.get("/healthz").status_code == 200
assert c.get("/docs").status_code == 200
print("ok: healthz/docs")
'@ | python -
  if ($LASTEXITCODE -ne 0) {
    throw "api smoke check failed"
  }
}
finally {
  Pop-Location
}

Write-Host "Acceptance backend checks passed."
