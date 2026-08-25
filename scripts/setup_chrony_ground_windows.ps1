[CmdletBinding()]
param(
    [string]$GroundIp,
    [string]$JetsonIp,
    [string[]]$Upstream = @(),
    [switch]$Rollback,
    [string]$BackupFile
)

$ErrorActionPreference = "Stop"

$FirewallRuleName = "Bengawan Ground NTP - Jetson"
$W32TimeRoot = "HKLM:\SYSTEM\CurrentControlSet\Services\W32Time"
$ParametersPath = Join-Path $W32TimeRoot "Parameters"
$ConfigPath = Join-Path $W32TimeRoot "Config"
$ServerProviderPath = Join-Path $W32TimeRoot "TimeProviders\NtpServer"
$ClientProviderPath = Join-Path $W32TimeRoot "TimeProviders\NtpClient"
$BackupRoot = Join-Path $env:ProgramData "Bengawan\chrony-windows\backups"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $admin = [Security.Principal.WindowsBuiltInRole]::Administrator
    if (-not $principal.IsInRole($admin)) {
        throw "Jalankan PowerShell dengan Run as administrator."
    }
}

function Assert-IPv4 {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $parts = $Value.Split('.')
    if ($parts.Count -ne 4) {
        throw "$Name bukan IPv4 yang valid: $Value"
    }
    foreach ($part in $parts) {
        if ($part -notmatch '^\d{1,3}$' -or ([int]$part -lt 0) -or ([int]$part -gt 255)) {
            throw "$Name bukan IPv4 yang valid: $Value"
        }
    }
}

function Set-RegistryDword {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Value
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -Path $Path -Force | Out-Null
    }
    New-ItemProperty -Path $Path -Name $Name -PropertyType DWord -Value $Value -Force | Out-Null
}

function Set-RegistryString {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowEmptyString()]
        [Parameter(Mandatory = $true)][string]$Value
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -Path $Path -Force | Out-Null
    }
    New-ItemProperty -Path $Path -Name $Name -PropertyType String -Value $Value -Force | Out-Null
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $false)][string[]]$ArgumentList = @()
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($ArgumentList -join ' ')"
    }
}

function Remove-BengawanFirewallRule {
    $rules = @(Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue)
    foreach ($rule in $rules) {
        Remove-NetFirewallRule -InputObject $rule -ErrorAction SilentlyContinue
    }
}

function Get-LatestBackup {
    if (-not (Test-Path -LiteralPath $BackupRoot)) {
        return $null
    }
    return Get-ChildItem -LiteralPath $BackupRoot -Filter "w32time-*.reg" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

function Invoke-Rollback {
    Assert-Administrator

    if ([string]::IsNullOrWhiteSpace($BackupFile)) {
        $latest = Get-LatestBackup
        if ($null -eq $latest) {
            throw "Backup W32Time tidak ditemukan di $BackupRoot"
        }
        $BackupFile = $latest.FullName
    }
    if (-not (Test-Path -LiteralPath $BackupFile)) {
        throw "Backup file tidak ditemukan: $BackupFile"
    }

    Remove-BengawanFirewallRule
    Invoke-NativeChecked "reg.exe" @("import", $BackupFile)
    Set-Service -Name W32Time -StartupType Automatic
    Restart-Service -Name W32Time -Force

    Write-Host "Rollback selesai dari: $BackupFile" -ForegroundColor Green
    & w32tm.exe /query /source
    & w32tm.exe /query /status
}

if ($Rollback) {
    Invoke-Rollback
    exit 0
}

if ([string]::IsNullOrWhiteSpace($GroundIp)) {
    throw "-GroundIp wajib diisi saat setup."
}
if ([string]::IsNullOrWhiteSpace($JetsonIp)) {
    throw "-JetsonIp wajib diisi saat setup."
}

Assert-Administrator
Assert-IPv4 -Value $GroundIp -Name "GroundIp"
Assert-IPv4 -Value $JetsonIp -Name "JetsonIp"

$localAddresses = @(
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
        ForEach-Object { $_.IPAddress }
)
if ($localAddresses -notcontains $GroundIp) {
    throw "GroundIp $GroundIp tidak ditemukan pada interface Windows ini. Periksa alamat Tailscale/LAN."
}

$computerSystem = Get-CimInstance -ClassName Win32_ComputerSystem
if ($computerSystem.PartOfDomain -and $Upstream.Count -eq 0) {
    throw "Windows ini tergabung domain. Berikan -Upstream agar domain time hierarchy tidak dimatikan."
}

New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$currentBackup = Join-Path $BackupRoot "w32time-$timestamp.reg"
Invoke-NativeChecked "reg.exe" @(
    "export",
    "HKLM\SYSTEM\CurrentControlSet\Services\W32Time",
    $currentBackup,
    "/y"
)

$hasUpstream = $Upstream.Count -gt 0
$announceFlags = if ($hasUpstream) { 10 } else { 5 }
$timeType = if ($hasUpstream) { "NTP" } else { "NoSync" }
$peerList = if ($hasUpstream) {
    (@($Upstream | ForEach-Object { "$($_),0x8" }) -join " ")
} else {
    ""
}

Write-Host "Configuring Windows Time as Ground NTP compatibility server..."
Set-RegistryString -Path $ParametersPath -Name "Type" -Value $timeType
Set-RegistryString -Path $ParametersPath -Name "NtpServer" -Value $peerList
Set-RegistryDword -Path $ConfigPath -Name "AnnounceFlags" -Value $announceFlags
Set-RegistryDword -Path $ServerProviderPath -Name "Enabled" -Value 1
Set-RegistryDword -Path $ClientProviderPath -Name "Enabled" -Value $(if ($hasUpstream) { 1 } else { 0 })

# w32tm /config requires the Windows Time service to be running. Start it
# before applying the reliable-source setting, then restart it again after the
# firewall rule has been installed.
Set-Service -Name W32Time -StartupType Automatic
$w32timeService = Get-Service -Name W32Time
if ($w32timeService.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Running) {
    Start-Service -Name W32Time
    Start-Sleep -Seconds 1
}

# Mark this host as the local reliable source. Re-apply AnnounceFlags after
# w32tm because /reliable can normalize the value on some Windows builds.
Invoke-NativeChecked "w32tm.exe" @("/config", "/reliable:yes", "/update")
Set-RegistryDword -Path $ConfigPath -Name "AnnounceFlags" -Value $announceFlags
Invoke-NativeChecked "w32tm.exe" @("/config", "/update")

Remove-BengawanFirewallRule
New-NetFirewallRule `
    -DisplayName $FirewallRuleName `
    -Description "Allow NTP requests from the Bengawan Jetson only." `
    -Direction Inbound `
    -Action Allow `
    -Protocol UDP `
    -LocalPort 123 `
    -RemoteAddress $JetsonIp `
    -Profile Any `
    -Enabled True | Out-Null

Set-Service -Name W32Time -StartupType Automatic
Restart-Service -Name W32Time -Force
Start-Sleep -Seconds 3

if ($hasUpstream) {
    & w32tm.exe /resync /force
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Upstream belum merespons; Windows tetap disiapkan sebagai local NTP source."
    }
}

Write-Host ""
Write-Host "Windows Ground NTP compatibility server siap." -ForegroundColor Green
Write-Host "Ground IP : $GroundIp"
Write-Host "Jetson IP : $JetsonIp"
Write-Host "Mode      : $timeType"
Write-Host "Backup    : $currentBackup"
Write-Host ""
Write-Host "Source/status Windows:"
& w32tm.exe /query /source
& w32tm.exe /query /status
Write-Host ""
Write-Host "Verifikasi read-only:"
Write-Host ".\scripts\verify_windows_time_server.ps1 -JetsonIp $JetsonIp"
Write-Host "Jetson harus diarahkan ke server $GroundIp dan menampilkan source ^*."
