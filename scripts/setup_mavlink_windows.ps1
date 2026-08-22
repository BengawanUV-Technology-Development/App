[CmdletBinding()]
param(
    [switch]$SkipPipUpgrade
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvDir = Join-Path $RepoRoot ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $RepoRoot "src-tauri\src-py\requirements.txt"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $false)][string[]]$ArgumentList = @()
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw ("Command failed with exit code {0}: {1} {2}" -f $LASTEXITCODE, $FilePath, ($ArgumentList -join " "))
    }
}

if (-not (Test-Path $PythonExe)) {
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $PyLauncher) {
        Invoke-Checked $PyLauncher.Source @("-3", "-m", "venv", $VenvDir)
    } else {
        $PythonLauncher = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $PythonLauncher) {
            throw "Python 3 tidak ditemukan. Install Python 3.10+ dan aktifkan opsi Add Python to PATH."
        }
        Invoke-Checked $PythonLauncher.Source @("-m", "venv", $VenvDir)
    }
}

if (-not $SkipPipUpgrade) {
    Invoke-Checked $PythonExe @("-m", "pip", "install", "--upgrade", "pip")
}

Invoke-Checked $PythonExe @("-m", "pip", "install", "-r", $Requirements)
Invoke-Checked $PythonExe @("-c", "import pymavlink; print('pymavlink OK')")

Write-Host ""
Write-Host "MAVLink Python environment siap." -ForegroundColor Green
Write-Host "Virtual environment: $VenvDir"
Write-Host ""
Write-Host "Langkah berikutnya:"
Write-Host "  1. Device Manager -> Ports untuk mencari port Pixhawk, misalnya COM5."
Write-Host "  2. Jalankan .\scripts\start_mavlink_router.ps1 -SerialPort COM5"
Write-Host "  3. Jalankan .\scripts\start_readonly_backend.ps1 pada terminal lain."
Write-Host "  4. Tambahkan UDP link 14550 di QGroundControl; jangan gunakan serial langsung."
