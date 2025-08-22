@echo off
setlocal

echo =======================================================
echo DropticalAPI GUI Build Script for Windows
echo =======================================================

REM Name of the virtual environment
set VENV_DIR=..\..\.venv

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python was not found in the PATH. Please install Python 3.
    exit /b 1
)

REM Create virtual environment if it doesn't exist
if not exist %VENV_DIR% (
    echo Creating virtual environment in '%VENV_DIR%'...
    python -m venv %VENV_DIR%
)

echo Activating virtual environment...
call %VENV_DIR%\Scripts\activate.bat

echo Installing dependencies from pyproject.toml...
pip install "../../.[gui]"

echo Starting PyInstaller build...
pyinstaller --noconfirm --clean dropticalGUI.spec

echo =======================================================
echo Build completed!
echo The finished application can be found in the 'dist' folder.
echo =======================================================

endlocal
pause
