<#
.SYNOPSIS
    Prepare the LAN demo after a change of box / router / Wi-Fi: finds the PC's IPv4 on the
    local network, lets Django accept it, writes the apps' initial API_URL / WS_URL, checks the
    port, and prints the address to type in the apps (no rebuild needed: « Changer de serveur »).

.DESCRIPTION
    See docs/reseau-local.md. What it does:
      1. finds the interface really connected to the box: adapter Up, IPv4 default gateway,
         private non-APIPA IPv4; ignores loopback, Bluetooth, VirtualBox / VMware host-only,
         Hyper-V / WSL (vEthernet) adapters. Several candidates: it STOPS and lists them
         (never picks one silently); choose with -InterfaceAlias "<name>" or -Ip <address>.
         -ListInterfaces only shows every adapter and why it is kept or ignored (changes nothing);
      2. writes DJANGO_ALLOWED_HOSTS in the repository's .env: localhost, 127.0.0.1, other
         non-IP names already there, and THIS address (the previous LAN address is removed);
         never "*". Nothing else of .env is read out or printed;
      3. writes mobile/config/lan.json (git-ignored): optional initial value for
         flutter run --dart-define-from-file=../../config/lan.json;
      4. with -Restart, recreates the `web` container so Django reads the new .env;
      5. checks http://<ip>:<port>/api/v1/health/, prints the Windows network profile and the
         firewall rules for the port (read only). It changes NO system setting: the admin
         commands are printed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File mobile\tools\configure_lan.ps1 -Restart
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File mobile\tools\configure_lan.ps1 -InterfaceAlias "Wi-Fi" -Restart
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File mobile\tools\configure_lan.ps1 -ListInterfaces
#>
param(
    [string]$Ip,
    [string]$InterfaceAlias,
    [int]$Port = 8000,
    [switch]$Restart,
    [switch]$ListInterfaces
)

$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$utf8 = New-Object System.Text.UTF8Encoding($false)  # .env must stay UTF-8 WITHOUT BOM (settings/base.py)
$virtual = 'Loopback|Bluetooth|VirtualBox|VMware|Hyper-V|vEthernet|WSL|Host-Only'

function Test-PrivateIPv4([string]$address) {
    $b = $address.Split('.') | ForEach-Object { [int]$_ }
    return ($b[0] -eq 10) -or ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31) -or ($b[0] -eq 192 -and $b[1] -eq 168)
}

# Why an interface is (not) the LAN of the box: '' = candidate.
function Get-Exclusion($config) {
    $name = "$($config.InterfaceAlias) $($config.InterfaceDescription)"
    $ipv4 = @($config.IPv4Address | ForEach-Object { $_.IPAddress })
    if ($name -match $virtual) { return "virtuelle ou non LAN ($($Matches[0]))" }
    if (-not $config.NetAdapter -or $config.NetAdapter.Status -ne 'Up') { return 'déconnectée' }
    if ($ipv4.Count -eq 0) { return 'pas d''IPv4' }
    if ($ipv4[0] -like '169.254.*') { return 'adresse automatique 169.254 (pas de box)' }
    if (-not (Test-PrivateIPv4 $ipv4[0])) { return 'IPv4 non privée' }
    if (-not $config.IPv4DefaultGateway) { return 'sans passerelle (pas de route vers la box)' }
    return ''
}

$configs = @(Get-NetIPConfiguration -All -ErrorAction SilentlyContinue)

if ($ListInterfaces) {
    foreach ($c in $configs) {
        $why = Get-Exclusion $c
        $ipv4 = @($c.IPv4Address | ForEach-Object { $_.IPAddress }) -join ','
        $verdict = if ($why) { "ignorée : $why" } else { 'CANDIDATE' }
        Write-Host ("{0,-28} {1,-16} {2}" -f $c.InterfaceAlias, $ipv4, $verdict)
    }
    return
}

# --- 1. The PC's address on the box's network ------------------------------------------------
$interface = $null
if ($InterfaceAlias) {
    $interface = $configs | Where-Object { $_.InterfaceAlias -eq $InterfaceAlias } | Select-Object -First 1
    if (-not $interface) { throw "Interface « $InterfaceAlias » introuvable. Liste : -ListInterfaces." }
    $why = Get-Exclusion $interface
    if ($why) { throw "Interface « $InterfaceAlias » inutilisable : $why." }
    $Ip = $interface.IPv4Address[0].IPAddress
} elseif (-not $Ip) {
    $candidates = @($configs | Where-Object { -not (Get-Exclusion $_) })
    if ($candidates.Count -eq 0) {
        throw 'Aucune interface reliée à une box (adaptateur actif, passerelle IPv4, adresse privée). Connectez le PC au Wi-Fi ; détail : -ListInterfaces.'
    }
    if ($candidates.Count -gt 1) {
        Write-Host 'Plusieurs interfaces sont reliées à un réseau local :'
        $candidates | ForEach-Object { Write-Host "    $($_.InterfaceAlias)  $($_.IPv4Address[0].IPAddress)  passerelle $($_.IPv4DefaultGateway.NextHop)" }
        throw 'Choix ambigu : relancez avec -InterfaceAlias "<nom>" (celle du Wi-Fi ou du câble de la box utilisé par les téléphones).'
    }
    $interface = $candidates[0]
    $Ip = $interface.IPv4Address[0].IPAddress
} elseif (-not (Test-PrivateIPv4 $Ip)) {
    throw "$Ip n'est pas une adresse privée de réseau local (192.168.x.x, 10.x.x.x, 172.16-31.x.x)."
}
if ($interface) {
    Write-Host "Interface retenue : $($interface.InterfaceAlias) ($($interface.InterfaceDescription))"
    Write-Host "IPv4 retenue      : $Ip   passerelle : $($interface.IPv4DefaultGateway.NextHop)"
} else {
    Write-Host "IPv4 imposée      : $Ip"
}

# --- 2. Django: accept this Host header, nothing wider -----------------------------------------
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) { throw ".env absent ($envFile) : copiez .env.example en .env d'abord." }
$lines = [System.IO.File]::ReadAllLines($envFile, $utf8)
$found = $false
$allowed = @()
$lines = $lines | ForEach-Object {
    if ($_ -match '^DJANGO_ALLOWED_HOSTS=(.*)$') {
        $found = $true
        $kept = $Matches[1].Split(',') | ForEach-Object { $_.Trim() } | Where-Object {
            $_ -and $_ -ne '*' -and -not ($_ -match '^\d{1,3}(\.\d{1,3}){3}$' -and $_ -ne '127.0.0.1')
        }
        $hosts = @('localhost', '127.0.0.1') + @($kept) + @($Ip) | Select-Object -Unique
        $script:allowed = $hosts
        'DJANGO_ALLOWED_HOSTS=' + ($hosts -join ',')
    } else { $_ }
}
if (-not $found) {
    $allowed = @('localhost', '127.0.0.1', $Ip)
    $lines += 'DJANGO_ALLOWED_HOSTS=' + ($allowed -join ',')
}
[System.IO.File]::WriteAllLines($envFile, [string[]]$lines, $utf8)
Write-Host ('Hôtes acceptés par Django (.env, DJANGO_ALLOWED_HOSTS seulement) : ' + ($allowed -join ', '))

# --- 3. Flutter: optional initial value for the four apps ---------------------------------------
$configDir = Join-Path $root 'mobile\config'
New-Item -ItemType Directory -Force $configDir | Out-Null
$json = "{`n  `"API_URL`": `"http://${Ip}:$Port/api/v1/`",`n  `"WS_URL`": `"ws://${Ip}:$Port/ws/v1/realtime/`"`n}`n"
[System.IO.File]::WriteAllText((Join-Path $configDir 'lan.json'), $json, $utf8)
Write-Host "mobile\config\lan.json (valeur initiale facultative) : API_URL=http://${Ip}:$Port/api/v1/"

# --- 4. Restart Django with the new .env -------------------------------------------------------
if ($Restart) {
    Push-Location $root
    # --no-deps: only Django is recreated (the database containers keep running).
    try { docker compose up -d --no-deps web } finally { Pop-Location }
}

# --- 5. Checks ------------------------------------------------------------------------------------
$todo = @()
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
    Write-Host "OK  http://${Ip}:$Port/api/v1/health/ -> $($health.StatusCode) (depuis ce PC)"
} else {
    Write-Warning "http://${Ip}:$Port/api/v1/health/ ne répond pas ($last). Django démarré ? .env relu (-Restart) ?"
    $todo += 'Faire répondre le serveur (docker compose up -d, puis -Restart).'
}

if ($interface) {
    $category = (Get-NetConnectionProfile -InterfaceAlias $interface.InterfaceAlias -ErrorAction SilentlyContinue).NetworkCategory
    Write-Host "Profil réseau Windows de $($interface.InterfaceAlias) : $category"
    if ($category -ne 'Private') {
        $todo += "Wi-Fi de confiance en profil Privé (PowerShell ADMINISTRATEUR) : Set-NetConnectionProfile -InterfaceAlias '$($interface.InterfaceAlias)' -NetworkCategory Private"
    }
}
# Inbound rules that open this port (read only: nothing is created, changed or removed).
$open = @(Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow -ErrorAction SilentlyContinue | Where-Object {
    $_.DisplayName -eq 'School Managing API (LAN)' -or $_.DisplayName -like 'Docker Desktop*'
})
foreach ($r in $open) { Write-Host "Pare-feu : « $($r.DisplayName) » autorise l'entrée, profil(s) $($r.Profile)" }
if (-not ($open | Where-Object { $_.DisplayName -eq 'School Managing API (LAN)' })) {
    $todo += "Règle du port $Port, profil Privé et sous-réseau local seulement (PowerShell ADMINISTRATEUR) : New-NetFirewallRule -DisplayName 'School Managing API (LAN)' -Direction Inbound -Protocol TCP -LocalPort $Port -Profile Private -RemoteAddress LocalSubnet -Action Allow"
}
if ($open | Where-Object { $_.DisplayName -like 'Docker Desktop*' -and "$($_.Profile)" -match 'Public|Any' }) {
    Write-Warning 'Des règles Docker Desktop ouvrent aussi le profil Public : à restreindre par l''administrateur du poste (docs/reseau-local.md). Rien n''est modifié ici.'
}

Write-Host ''
Write-Host "Adresse à saisir dans les applications : http://${Ip}:$Port"
Write-Host '    Application → « Changer de serveur » (connexion) ou Profil → « Serveur » → Tester → Enregistrer.'
Write-Host '    (Aucune recompilation. Valeur initiale facultative : flutter run --dart-define-from-file=../../config/lan.json)'
Write-Host ''
Write-Host 'Vérifications restantes :'
$todo += "Depuis le téléphone (même Wi-Fi, pas le réseau invité) : ouvrir http://${Ip}:$Port/api/v1/health/ ou « Tester la connexion »."
$todo | ForEach-Object { Write-Host "  - $_" }
