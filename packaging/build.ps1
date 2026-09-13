<#
FaceScan v1.0.0 build pipeline:
  1. Tests
  2. Branding resources (ico + wizard) and version_info.txt
  3. Facial model staging (buffalo_l)
  4. PyInstaller (onedir -> dist\FaceScan)
  5. Inno Setup installer (FaceScan-Setup-1.0.0.exe)

Usage:
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Py)) {
    throw "No se encontro .venv\Scripts\python.exe"
}

Write-Host "==> 1/6 Tests"
& $Py -m pytest -q --no-header -p no:warnings
if ($LASTEXITCODE -ne 0) { throw "Tests fallidos" }

Write-Host "==> 2/6 Recursos de marca y version_info"
& $Py packaging\make_icons.py
if ($LASTEXITCODE -ne 0) { throw "make_icons fallo" }
& $Py packaging\make_version_info.py
if ($LASTEXITCODE -ne 0) { throw "make_version_info fallo" }

Write-Host "==> 3/6 Modelos faciales (staging)"
if (-not (Test-Path "models\buffalo_l")) {
    $src = Join-Path $env:USERPROFILE ".insightface\models\buffalo_l"
    if (Test-Path $src) {
        New-Item -ItemType Directory -Force -Path "models" | Out-Null
        Copy-Item -Recurse $src "models\buffalo_l"
        Write-Host "    modelos copiados desde $src"
    }
    else {
        Write-Warning "No se hallaron modelos en $src; se empaquetara sin ellos (descarga en el primer uso)."
    }
}

Write-Host "==> 4/6 PyInstaller"
& $Py -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller no instalado. Ejecuta: .venv\Scripts\pip install pyinstaller"
}
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "build", "dist\FaceScan"
& $Py -m PyInstaller packaging\facescan.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo" }

Write-Host "==> 5/6 Instalador Inno Setup"
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $isccPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $isccPath) {
        throw "ISCC.exe no encontrado. Instala Inno Setup 6 y anade su carpeta al PATH."
    }
    & $isccPath packaging\installer.iss
}
else {
    & $iscc packaging\installer.iss
}
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallo" }

Write-Host "==> 6/6 Completado"
Get-ChildItem dist\*.exe | Select-Object Name, Length