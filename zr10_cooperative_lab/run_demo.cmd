@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please follow README.md to create .venv and install the project first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m zr10lab run --config configs/four_zr10.yaml --duration 60
pause
