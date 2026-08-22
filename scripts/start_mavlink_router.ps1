[CmdletBinding()]
param(
    [string]$SerialPort = "COM5",
    [int]$Baud = 57600,
    [string]$QgcAddress = "127.0.0.1:14550",
    [string]$WebAddress = "127.0.0.1:14551"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Router = Join-Path $PSScriptRoot "mavlink_readonly_router.py"

if ($env:MAVLINK_SERIAL_PORT) {
    $SerialPort = $env:MAVLINK_SERIAL_PORT
}
if ($env:MAVLINK_SERIAL_BAUD) {
    $Baud = [int]$env:MAVLINK_SERIAL_BAUD
}

if (-not (Test-Path $PythonExe)) {
    throw "Virtual environment belum ada. Jalankan .\scripts\setup_mavlink_windows.ps1 terlebih dahulu."
}

Write-Host "Starting read-only MAVLink router..." -ForegroundColor Cyan
Write-Host "Serial: $SerialPort @ $Baud"
Write-Host "QGC:    $QgcAddress (bidirectional)"
Write-Host "Web:    $WebAddress (telemetry-only)"

$RouterArgs = @(
    "--serial", $SerialPort,
    "--baud", [string]$Baud,
    "--qgc", $QgcAddress,
    "--web", $WebAddress
)

& $PythonExe $Router @RouterArgs

exit $LASTEXITCODE
