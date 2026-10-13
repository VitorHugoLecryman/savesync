# Gera o instalador Instalador\SaveSync-Setup-<versão>.exe
# Uso:  powershell -ExecutionPolicy Bypass -File build_installer.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Host "Instalando o Inno Setup (ferramenta gratuita que cria o instalador)..."
    winget install --id JRSoftware.InnoSetup -e --scope user --silent --accept-package-agreements --accept-source-agreements
    $iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
}

& powershell -ExecutionPolicy Bypass -File build_exe.ps1
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o executável" }

$version = (Select-String -Path savesync\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
& $iscc /Q "/DAppVersion=$version" installer\SaveSync.iss
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o instalador" }

Remove-Item build, SaveSync.spec -Recurse -Force -ErrorAction SilentlyContinue
$out = Get-Item "Instalador\SaveSync-Setup-$version.exe"
Write-Host ("Pronto: {0}  ({1:N0} MB)" -f $out.FullName, ($out.Length / 1MB)) -ForegroundColor Green
