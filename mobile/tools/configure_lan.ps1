<#
.SYNOPSIS
    Prepare the LAN demo after a change of box / router / Wi-Fi: finds the PC's IPv4 on the
    local network, lets Django accept it, writes the apps' API_URL / WS_URL, checks the port.

.DESCRIPTION
    See docs/reseau-local.md. What it does:
      1. finds the IPv4 of the interface that has a default gateway (the box), ignoring
         VirtualBox / Hyper-V / APIPA (169.254.x.x) adapters; -Ip forces an address;
      2. writes DJANGO_ALLOWED_HOSTS in the repository's .env: localhost, 127.0.0.1, other
         non-IP names already there, and THIS address (the previous LAN address is removed);
         never "*";
      3. writes mobile/config/lan.json (git-ignored) for
         flutter run --dart-define-from-file=../../config/lan.json;
      4. with -Restart, recreates the `web` container so Django reads the new .env;
      5. checks http://<ip>:<port>/api/v1/health/ and prints the Windows network profile and
         firewall situation. It changes NO system setting: the admin commands are printed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File mobile\tools\configure_lan.ps1 -Restart
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File mobile\tools\configure_lan.ps1 -Ip 192.168.0.42 -Restart
#>
param(
    [string]$Ip,
    [int]$Port = 8000,
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$utf8 = New-Object System.Text.UTF8Encoding($false)  # .env must stay UTF-8 WITHOUT BOM (settings/base.py)

function Test-PrivateIPv4([string]$address) {
    $b = $address.Split('.') | ForEach-Object { [int]$_ }
    return ($b[0] -eq 10) -or ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31) -or ($b[0] -eq 192 -and $b[1] -eq 168)
}

# --- 1. The PC's address on the box's network ------------------------------------------------
$interface = $null
if (-not $Ip) {
    $candidates = Get-NetIPConfiguration | Where-Object {
        $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' -and
        $_.InterfaceDescription -notmatch 'VirtualBox|Hyper-V|VMware|WSL' -and
        $_.IPv4Address.IPAddress -notlike '169.254.*'
    }
    $candidates = @($candidates | Where-Object { Test-PrivateIPv4 $_.IPv4Address[0].IPAddress })
    if ($candidates.Count -eq 0) { throw 'Aucune interface reliée à une box (passerelle IPv4) : connectez le PC au Wi-Fi, ou passez -Ip.' }
    if ($candidates.Count -gt 1) {
        Write-Warning ('Plusieurs interfaces reliées : ' + (($candidates | ForEach-Object { "$($_.InterfaceAlias)=$($_.IPv4Address[0].IPAddress)" }) -join ', ') + ". La première est utilisée ; -Ip pour choisir.")
    }
    $interface = $candidates[0]
    $Ip = $interface.IPv4Address[0].IPAddress
    Write-Host "Interface : $($interface.InterfaceAlias)  IPv4 : $Ip  passerelle : $($interface.IPv4DefaultGateway.NextHop)"
} elseif (-not (Test-PrivateIPv4 $Ip)) {
    throw "$Ip n'est pas une adresse privée de réseau local (192.168.x.x, 10.x.x.x, 172.16-31.x.x)."
}

# --- 2. Django: accept this Host header, nothing wider -----------------------------------------
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) { throw ".env absent ($envFile) : copiez .env.example en .env d'abord." }
$lines = [System.IO.File]::ReadAllLines($envFile, $utf8)
$found = $false
$lines = $lines | ForEach-Object {
    if ($_ -match '^DJANGO_ALLOWED_HOSTS=(.*)$') {
        $found = $true
        $kept = $Matches[1].Split(',') | ForEach-Object { $_.Trim() } | Where-Object {
            $_ -and $_ -ne '*' -and -not ($_ -match '^\d{1,3}(\.\d{1,3}){3}$' -and $_ -ne '127.0.0.1')
        }
        $hosts = @('localhost', '127.0.0.1') + @($kept) + @($Ip) | Select-Object -Unique
        'DJANGO_ALLOWED_HOSTS=' + ($hosts -join ',')
    } else { $_ }
}
if (-not $found) { $lines += "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,$Ip" }
[System.IO.File]::WriteAllLines($envFile, [string[]]$lines, $utf8)
Write-Host ('.env : ' + ($lines | Where-Object { $_ -like 'DJANGO_ALLOWED_HOSTS=*' }))

# --- 3. Flutter: one file for the four apps ----------------------------------------------------
$configDir = Join-Path $root 'mobile\config'
New-Item -ItemType Directory -Force $configDir | Out-Null
$json = "{`n  `"API_URL`": `"http://${Ip}:$Port/api/v1/`",`n  `"WS_URL`": `"ws://${Ip}:$Port/ws/v1/realtime/`"`n}`n"
[System.IO.File]::WriteAllText((Join-Path $configDir 'lan.json'), $json, $utf8)
Write-Host "mobile\config\lan.json : API_URL=http://${Ip}:$Port/api/v1/"

# --- 4. Restart Django with the new .env -------------------------------------------------------
if ($Restart) {
    Push-Location $root
    # --no-deps: only Django is recreated (the database containers keep running).
    try { docker compose up -d --no-deps web } finally { Pop-Location }
}

# --- 5. Checks ------------------------------------------------------------------------------------
$health = $null
$last = ''
for ($i = 0; $i -lt 30 -and -not $health; $i++) {  # Django runs its migrations first: up to ~90 s
    try {
        $health = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://${Ip}:$Port/api/v1/health/"
    } catch {
        $last = $_.Exception.Message
        Start-Sleep -Seconds 3
    }
}
if ($health) {
    Write-Host "OK  http://${Ip}:$Port/api/v1/health/ -> $($health.StatusCode)"
} else {
    Write-Warning "http://${Ip}:$Port/api/v1/health/ ne répond pas ($last). Django démarré ? .env relu (-Restart) ?"
}

if ($interface) {
    $category = (Get-NetConnectionProfile -InterfaceAlias $interface.InterfaceAlias).NetworkCategory
    Write-Host "Profil réseau Windows de $($interface.InterfaceAlias) : $category"
    if ($category -ne 'Private') {
        Write-Warning "Le réseau est '$category'. Pour un Wi-Fi d'école/maison de confiance, en PowerShell ADMINISTRATEUR :"
        Write-Host "    Set-NetConnectionProfile -InterfaceAlias '$($interface.InterfaceAlias)' -NetworkCategory Private"
    }
}
$rule = Get-NetFirewallRule -DisplayName 'School Managing API (LAN)' -ErrorAction SilentlyContinue
if (-not $rule) {
    Write-Host "Pare-feu : aucune règle 'School Managing API (LAN)'. En PowerShell ADMINISTRATEUR (profil Privé seulement) :"
    Write-Host "    New-NetFirewallRule -DisplayName 'School Managing API (LAN)' -Direction Inbound -Protocol TCP -LocalPort $Port -Profile Private -RemoteAddress LocalSubnet -Action Allow"
}
Write-Host ''
Write-Host 'Applications (depuis mobile\apps\<app>) :'
Write-Host '    flutter run --dart-define-from-file=../../config/lan.json'
