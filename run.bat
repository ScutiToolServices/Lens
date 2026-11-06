@echo off
REM Starts the Lens service on port 8093 (syncs .venv with uv on each run).
REM LABEL: Lens Service
REM DESCRIPTION: Tesseract OCR HTTP and MCP tool server (CPU only, fast and accurate modes).

cd /d "%~dp0"

uv sync
if errorlevel 1 (
    echo uv sync failed. Install uv: winget install astral-sh.uv
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat

if not defined TESSERACT_CMD if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe"
python -m src.models
if errorlevel 1 (
    echo Model download failed. Install Tesseract: winget install --id UB-Mannheim.Lens --exact
    pause
    exit /b 1
)
python -m src.run
pause
