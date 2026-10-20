# Build of the Windows admin client: packaged program + installer (docs/desktop-windows.md).
#
#   cd desktop
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Needs: desktop\.venv with requirements.txt, PyInstaller (packaging\requirements-build.txt)
# and Inno Setup 6 (ISCC.exe). Writes, in desktop\packaging\dist\ (not versioned):
#   SchoolManagingAdmin\SchoolManagingAdmin.exe        packaged program (no Python needed)
#   installer\SchoolManagingAdmin-Setup-<version>-x64.exe
$ErrorActionPreference = "Stop"
$desktop = Split-Path -Parent $PSScriptRoot
$packaging = $PSScriptRoot
$python = Join-Path $desktop ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "desktop\.venv is missing: see desktop\README.md" }

# Version: the program's own (school_admin/__init__.py), the only source.
$version = & $python -c "import sys; sys.path.insert(0, r'$desktop'); import school_admin; print(school_admin.__version__)"
if ($LASTEXITCODE -ne 0 -or -not $version) { throw "Cannot read school_admin.__version__" }
Write-Host "Version $version"

$build = Join-Path $packaging "build"
New-Item -ItemType Directory -Force $build | Out-Null

# 1. Icon (ISBREE monogram) and Windows version information of the .exe.
& $python (Join-Path $packaging "make_icon.py")
if ($LASTEXITCODE -ne 0) { throw "make_icon.py failed" }
$parts = ($version.Split(".") + @("0", "0", "0"))[0..3] -join ", "
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts), prodvers=($parts)),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
      StringStruct('CompanyName', 'School Managing'),
      StringStruct('FileDescription', "Client d'administration School Managing"),
      StringStruct('FileVersion', '$version'),
      StringStruct('ProductName', 'School Managing Admin'),
      StringStruct('ProductVersion', '$version'),
      StringStruct('OriginalFilename', 'SchoolManagingAdmin.exe')])]),
    VarFileInfo([VarStruct('Translation', [1036, 1200])])
  ]
)
"@ | Set-Content -Encoding utf8 (Join-Path $build "version_info.txt")

# 2. Packaged program (one folder).
Push-Location $desktop
try {
  & $python -m PyInstaller (Join-Path $packaging "school_admin.spec") --noconfirm --clean `
    --distpath (Join-Path $packaging "dist") --workpath (Join-Path $build "pyinstaller")
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
} finally { Pop-Location }
$exe = Join-Path $packaging "dist\SchoolManagingAdmin\SchoolManagingAdmin.exe"
if (-not (Test-Path $exe)) { throw "Missing $exe" }

# 3. Installer.
$iscc = @(
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) not found: winget install JRSoftware.InnoSetup" }
& $iscc "/DAppVersion=$version" (Join-Path $packaging "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }

$setup = Join-Path $packaging "dist\installer\SchoolManagingAdmin-Setup-$version-x64.exe"
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
$size = [math]::Round((Get-Item $setup).Length / 1MB, 1)
Write-Host "Installer: $setup ($size MB)"
Write-Host "SHA-256  : $hash"
