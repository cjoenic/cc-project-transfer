param([string]$Python = "$PSScriptRoot\.venv\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$localTcl = Join-Path $PSScriptRoot 'build\tcl'
if (Test-Path -LiteralPath (Join-Path $localTcl 'tk8.6\tk.tcl')) {
    $env:TCL_LIBRARY = (Join-Path $localTcl 'tcl8.6').Replace('\', '/')
    $env:TK_LIBRARY = (Join-Path $localTcl 'tk8.6').Replace('\', '/')
}
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot 'build\pyinstaller-cache'
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --add-data "splash-v2.png;." --copy-metadata send2trash --copy-metadata pywin32 --name "CC Project Transfer v2.0" app.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Portable app: $PSScriptRoot\dist\CC Project Transfer v2.0.exe"
