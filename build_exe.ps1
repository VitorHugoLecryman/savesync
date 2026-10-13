# Gera dist\SaveSync\SaveSync.exe (não precisa de Python instalado para rodar).
# Uso:  powershell -ExecutionPolicy Bypass -File build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --quiet -r requirements.txt pyinstaller
& $py tools\make_icon.py

$exclude = @("QtWebEngineCore", "QtWebEngineWidgets", "QtQuick", "QtQml", "Qt3DCore", "QtMultimedia",
             "QtCharts", "QtDataVisualization", "QtPdf", "QtSql", "QtTest", "QtBluetooth", "QtPositioning",
             "QtSensors", "QtSerialPort", "QtDesigner", "QtOpenGL", "QtOpenGLWidgets", "QtSvg", "tkinter") |
           ForEach-Object { "--exclude-module"; if ($_ -eq "tkinter") { $_ } else { "PySide6.$_" } }

& $py -m PyInstaller --noconfirm --clean --windowed --onedir --name SaveSync `
    --icon assets\savesync.ico @exclude main.py

# Enxuga o pacote: só o documento da API do Drive e só as partes do Qt que o app usa
$int = "dist\SaveSync\_internal"
Get-ChildItem "$int\googleapiclient\discovery_cache\documents" -Filter *.json |
    Where-Object Name -ne "drive.v3.json" | Remove-Item
$qt = "$int\PySide6"
$remove = @("opengl32sw.dll", "Qt6Pdf.dll", "Qt6Qml.dll", "Qt6QmlMeta.dll", "Qt6QmlModels.dll",
            "Qt6QmlWorkerScript.dll", "Qt6Quick.dll", "Qt6VirtualKeyboard.dll", "Qt6OpenGL.dll",
            "plugins\imageformats\qpdf.dll", "plugins\platforminputcontexts", "plugins\generic",
            "plugins\platforms\qdirect2d.dll", "plugins\platforms\qoffscreen.dll", "plugins\imageformats\qtiff.dll",
            "plugins\imageformats\qwebp.dll", "plugins\imageformats\qicns.dll", "plugins\imageformats\qtga.dll")
foreach ($r in $remove) { if (Test-Path "$qt\$r") { Remove-Item "$qt\$r" -Recurse -Force } }
Get-ChildItem "$qt\translations" -File | Where-Object Name -notmatch "_pt" | Remove-Item

# Embute a credencial OAuth do Google (client_secret_*.json na pasta do projeto), para quem
# instalar só precisar entrar com a própria conta. Ela fica em _internal\credentials.json.
$secret = Get-ChildItem client_secret_*.json -ErrorAction SilentlyContinue | Select-Object -First 1
if ($secret) {
    $json = Get-Content $secret.FullName -Raw | ConvertFrom-Json
    if (-not $json.installed) { throw "$($secret.Name) não é do tipo 'App para computador'." }
    Copy-Item $secret.FullName "$int\credentials.json"
    Write-Host "Credencial do Google embutida ($($json.installed.project_id))" -ForegroundColor Cyan
} else {
    Write-Host "Aviso: nenhum client_secret_*.json na pasta; quem instalar terá que configurar o Google Cloud." -ForegroundColor Yellow
}

$size = (Get-ChildItem dist\SaveSync -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ""
Write-Host ("Pronto: dist\SaveSync\SaveSync.exe  ({0:N0} MB)" -f $size) -ForegroundColor Green
