@echo off
cd /d "%~dp0"
if exist "dist\InkCompanion-1.5\InkCompanion-1.5.exe" (
  start "" "dist\InkCompanion-1.5\InkCompanion-1.5.exe"
  exit /b
)
if exist "dist\InkCompanion-1.4\InkCompanion-1.4.exe" (
  start "" "dist\InkCompanion-1.4\InkCompanion-1.4.exe"
  exit /b
)
if exist "dist\InkCompanion-1.3\InkCompanion-1.3.exe" (
  start "" "dist\InkCompanion-1.3\InkCompanion-1.3.exe"
  exit /b
)
if exist "dist\InkCompanion-1.2\InkCompanion-1.2.exe" (
  start "" "dist\InkCompanion-1.2\InkCompanion-1.2.exe"
  exit /b
)
if exist "dist\InkCompanion-1.1\InkCompanion-1.1.exe" (
  start "" "dist\InkCompanion-1.1\InkCompanion-1.1.exe"
  exit /b
)
if exist "dist\InkCompanion-1.0\InkCompanion-1.0.exe" (
  start "" "dist\InkCompanion-1.0\InkCompanion-1.0.exe"
  exit /b
)
if exist "dist\InkCompanion-BLE-ReadOnly\InkCompanion-BLE-ReadOnly.exe" (
  start "" "dist\InkCompanion-BLE-ReadOnly\InkCompanion-BLE-ReadOnly.exe"
  exit /b
)
if exist "dist\InkCompanion\InkCompanion.exe" (
  start "" "dist\InkCompanion\InkCompanion.exe"
  exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "app.py"
  exit /b
)
echo Please install Python 3.13 and run setup.ps1 first.
pause
