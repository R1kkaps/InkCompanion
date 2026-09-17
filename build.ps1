param([string]$Name = 'InkCompanion-1.5')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --onedir --name $Name --collect-submodules winrt.windows.media --collect-submodules winrt.windows.storage.streams --collect-submodules winrt.windows.foundation --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module matplotlib --exclude-module numpy --exclude-module pandas --exclude-module scipy --exclude-module IPython app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
