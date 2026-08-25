[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$JetsonIp
)

$ErrorActionPreference = "Stop"
$FirewallRuleName = "Bengawan Ground NTP - Jetson"
$W32TimeRoot = "HKLM:\SYSTEM\CurrentControlSet\Services\W32Time"
$ConfigPath = Join-Path $W32TimeRoot "Config"
$ServerProviderPath = Join-Path $W32TimeRoot "TimeProviders\NtpServer"

function Assert-IPv4 {
    param([Parameter(Mandatory = $true)][string]$Value)
    $parts = $Value.Split('.')
    if ($parts.Count -ne 4) {
        throw "JetsonIp bukan IPv4 yang valid: $Value"
    }
    foreach ($part in $parts) {
        if ($part -notmatch '^\d{1,3}$' -or ([int]$part -lt 0) -or ([int]$part -gt 255)) {
            throw "JetsonIp bukan IPv4 yang valid: $Value"
        }
    }
}

function Invoke-W32tmQuery {
    param([Parameter(Mandatory = $true)][string[]]$ArgumentList)
    $output = & w32tm.exe @ArgumentList 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "w32tm query gagal: $($ArgumentList -join ' ')`n$output"
    }
    return $output.Trim()
}

Assert-IPv4 -Value $JetsonIp
$service = Get-Service -Name W32Time
$config = Get-ItemProperty -Path $ConfigPath
$serverProvider = Get-ItemProperty -Path $ServerProviderPath
$rules = @(Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue)
$remoteAddresses = @()
foreach ($rule in $rules) {
    $filter = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule
    $remoteAddresses += @($filter.RemoteAddress)
}

$serviceOk = $service.Status -eq [System.ServiceProcess.ServiceControllerStatus]::Running
$providerOk = [int]$serverProvider.Enabled -eq 1
$announceOk = @([int]$config.AnnounceFlags) -contains 5 -or @([int]$config.AnnounceFlags) -contains 10
$firewallOk = @(
    $rules | Where-Object {
        $_.Enabled -eq "True" -and $_.Action -eq "Allow"
    }
).Count -gt 0 -and ($remoteAddresses -contains $JetsonIp)

$source = Invoke-W32tmQuery -ArgumentList @("/query", "/source")
$status = Invoke-W32tmQuery -ArgumentList @("/query", "/status")
$configuration = Invoke-W32tmQuery -ArgumentList @("/query", "/configuration")

$report = [ordered]@{
    ok = ($serviceOk -and $providerOk -and $announceOk -and $firewallOk)
    role = "windows-ground-ntp-compatibility"
    service = $service.Status.ToString()
    source = $source
    announce_flags = [int]$config.AnnounceFlags
    ntp_server_enabled = $providerOk
    firewall_rule_present = ($rules.Count -gt 0)
    firewall_remote_addresses = $remoteAddresses
    jetson_ip = $JetsonIp
    status = $status
    configuration = $configuration
}

$report | ConvertTo-Json -Depth 5
if (-not $report.ok) {
    exit 1
}
