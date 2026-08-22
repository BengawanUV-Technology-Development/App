[CmdletBinding()]
param(
    [string]$ApiHost = "127.0.0.1",
    [int]$ApiPort = 5001,
    [string]$MavlinkHost = "127.0.0.1",
    [int]$MavlinkPort = 14551
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$BackendDir = Join-Path $RepoRoot "src-tauri\src-py"
$Main = Join-Path $BackendDir "main.py"

if (-not (Test-Path $PythonExe)) {
    throw "Virtual environment belum ada. Jalankan .\scripts\setup_mavlink_windows.ps1 terlebih dahulu."
}

$env:PYTHONPATH = $BackendDir
$env:API_HOST = $ApiHost
$env:API_PORT = [string]$ApiPort
$env:MAVLINK_UDP_HOST = $MavlinkHost
$env:MAVLINK_UDP_PORT = [string]$MavlinkPort

Write-Host "Starting telemetry-only backend..." -ForegroundColor Cyan
Write-Host ("HTTP:    {0}:{1}" -f $ApiHost, $ApiPort)
Write-Host ("MAVLink: udpin://{0}:{1}" -f $MavlinkHost, $MavlinkPort)
Write-Host "Commands: disabled; use QGroundControl on UDP 14550." -ForegroundColor Yellow

& $PythonExe $Main

exit $LASTEXITCODE
