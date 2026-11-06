@echo off
REM Starts the Lens service on port 8093 (syncs .venv with uv on each run).
REM LABEL: Lens Service
REM DESCRIPTION: Image OCR HTTP and MCP tool server; recognition runs on a TesseractModel service.

cd /d "%~dp0"

uv sync
if errorlevel 1 (
    echo uv sync failed. Install uv: winget install astral-sh.uv
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat

python -m src.run
pause
