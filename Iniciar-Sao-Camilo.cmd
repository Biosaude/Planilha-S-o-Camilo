@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Aplicativo nao instalado. Execute scripts\Instalar-Windows11.ps1 no PowerShell.
  pause
  exit /b 1
)
if not exist "data\tuss.sqlite3" (
  echo Banco TUSS ausente. Importe as duas bases privadas antes de iniciar.
  pause
  exit /b 1
)
set "BIOSAUDE_AUTH_MODE=public"
set "BIOSAUDE_TUSS_DB=%CD%\data\tuss.sqlite3"
set "BIOSAUDE_AUDIT_DB=%CD%\data\audit.sqlite3"
echo Abrindo aplicativo em http://127.0.0.1:8501
start "" "http://127.0.0.1:8501"
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
echo.
echo Aplicativo encerrado.
pause
