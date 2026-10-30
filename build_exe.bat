@echo off
REM 一键构建单文件 EXE。首次构建前需安装 PyInstaller：
REM   venv\Scripts\python.exe -m pip install pyinstaller
cd /d "%~dp0"

venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile ^
  --name PikPakDiskTool ^
  --add-data "%~dp0templates;templates" ^
  app.py

if errorlevel 1 (
    echo.
    echo [失败] 构建出错，请看上方日志
    pause
    exit /b 1
)

copy /Y dist\PikPakDiskTool.exe PikPakDiskTool.exe >nul
echo.
echo [完成] 已生成：%~dp0PikPakDiskTool.exe
echo 双击即可运行（数据与配置在 exe 旁边的 data\ 和 config_local.py）
pause
