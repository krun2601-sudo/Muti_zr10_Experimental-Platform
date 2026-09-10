@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 未找到项目自己的 .venv 环境。
  echo 请先在此目录创建 Python 环境并按 requirements.txt 安装依赖。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m zr10lab console --config "configs\control_center.yaml"
if errorlevel 1 pause
