@echo off
setlocal

cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv was not found in PATH.
    echo         Install uv: https://docs.astral.sh/uv/
    pause
    exit /b 1
)

echo ============================================================
echo  Irodori VoiceSetBuilder
echo  URL: http://127.0.0.1:7860
echo  TTS server default: http://127.0.0.1:5000
echo  Stop: Ctrl+C
echo ============================================================
echo.

uv run --locked python app.py
set "BUILDER_EXIT_CODE=%ERRORLEVEL%"

if not "%BUILDER_EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Builder exited with code %BUILDER_EXIT_CODE%.
    pause
)
exit /b %BUILDER_EXIT_CODE%
