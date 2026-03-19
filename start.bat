@echo off
cd /d "%~dp0"
echo ========================================
echo   Receipt Bot
echo ========================================

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+
    pause
    exit /b 1
)

:: Check .env
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo Copy .env.example to .env and fill in your tokens.
    pause
    exit /b 1
)

:: Kill any running instance of this bot
wmic process where "name='python.exe' and CommandLine like '%%main.py%%'" call terminate >nul 2>&1
timeout /t 1 /nobreak >nul

:: Install dependencies if needed
pip install -r requirements.txt -q

echo [OK] Starting bot...
echo Press Ctrl+C to stop
echo.
python main.py

pause
