# start.ps1 - one command to (re)start the whole payout system.
#
#   .\start.ps1          # frees ports, then launches backend + frontend dev server
#   .\start.ps1 -Build   # build the production frontend bundle first
#
# Opens two windows: Backend (uvicorn :8000) and Frontend (Vite :5173).
# Re-running is safe - it kills whatever is already on those ports first,
# so you never hit the "address already in use" error again.

param([switch]$Build)

$root = $PSScriptRoot
$venv = "C:\payout_venv\Scripts\Activate.ps1"

# Keep the live DB OFF OneDrive - OneDrive syncing a SQLite file mid-write
# corrupts it (this has bitten us twice). PAYOUT_DB is inherited by the
# backend window launched below.
$env:PAYOUT_DB = "C:\payout_data\payout.db"
if (-not (Test-Path "C:\payout_data")) { New-Item -ItemType Directory -Path "C:\payout_data" -Force | Out-Null }

function Free-Port($port) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($procId in ($conns.OwningProcess | Select-Object -Unique)) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host "[start] freed port $port (stopped PID $procId)" -ForegroundColor Yellow
    }
}

Write-Host "[start] freeing ports 8000 and 5173..." -ForegroundColor Cyan
Free-Port 8000
Free-Port 5173
Start-Sleep -Milliseconds 600

if ($Build) {
    Write-Host "[start] building frontend bundle..." -ForegroundColor Cyan
    Push-Location "$root\frontend"; npm run build; Pop-Location
}

# Backend (uvicorn) in its own window.
Write-Host "[start] launching backend  -> http://localhost:8000" -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "& '$venv'; Set-Location '$root'; `$env:PAYOUT_DB='C:\payout_data\payout.db'; uvicorn payout.api.app:app"
)

# Frontend (Vite dev server) in its own window.
Write-Host "[start] launching frontend -> http://localhost:5173" -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\frontend'; npm run dev"
)

Write-Host ""
Write-Host "[start] Both starting in new windows. Open the app at:" -ForegroundColor Cyan
Write-Host "        http://localhost:5173   (hard-refresh: Ctrl+Shift+R)" -ForegroundColor Cyan
Write-Host "        Close a window or Ctrl+C in it to stop that service." -ForegroundColor DarkGray
