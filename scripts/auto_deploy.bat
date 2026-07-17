@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  auto_deploy.bat - Deploy automatico diario del SME
REM  Ejecutado por Task Scheduler a las 5:00 AM
REM ============================================================

cd /d "C:\Users\artur\sme-motel"

set LOG=logs\auto_deploy.log
set TIMESTAMP=%date% %time%

echo. >> %LOG%
echo ========================================== >> %LOG%
echo [%TIMESTAMP%] Iniciando auto-deploy >> %LOG%
echo ========================================== >> %LOG%

REM --- Guardar hash antes del pull ---
for /f %%i in ('git rev-parse HEAD') do set HASH_ANTES=%%i
echo [INFO] Hash antes: !HASH_ANTES! >> %LOG%

REM --- Fetch + reset a origin/main (descarta cambios en archivos tracked) ---
REM NO usamos git clean para no borrar archivos locales como los .bat
git fetch origin main >> %LOG% 2>&1
git reset --hard origin/main >> %LOG% 2>&1

REM --- Guardar hash despues ---
for /f %%i in ('git rev-parse HEAD') do set HASH_DESPUES=%%i
echo [INFO] Hash despues: !HASH_DESPUES! >> %LOG%

REM --- Si no hubo cambios, terminar ---
if "!HASH_ANTES!"=="!HASH_DESPUES!" (
    echo [INFO] No hay cambios nuevos. Terminando. >> %LOG%
    goto :fin
)

echo [OK] Cambios detectados. Aplicando deploy. >> %LOG%

REM --- pip install (idempotente) ---
echo [INFO] Ejecutando pip install... >> %LOG%
venv\Scripts\python.exe -m pip install -r requirements.txt >> %LOG% 2>&1

REM --- Migraciones de BD (idempotente) ---
echo [INFO] Ejecutando init_db.py... >> %LOG%
venv\Scripts\python.exe scripts\init_db.py >> %LOG% 2>&1

REM --- Detectar si hubo cambios en archivos .py ---
git diff --name-only !HASH_ANTES! !HASH_DESPUES! | findstr /I /L ".py" > nul
if !errorlevel! equ 0 (
    echo [INFO] Cambios en .py detectados. Reiniciando Waitress... >> %LOG%
    
    REM Matar Waitress actual (arbol completo: waitress-serve.exe + python.exe hijos que tienen el puerto)
    taskkill /F /T /IM waitress-serve.exe >> %LOG% 2>&1
    timeout /t 2 /nobreak > nul
    
    REM Arrancar Waitress de nuevo
    start /min cmd /c "venv\Scripts\waitress-serve.exe --call --host=0.0.0.0 --port=5050 app:create_app"
    echo [OK] Waitress reiniciado. >> %LOG%
) else (
    echo [INFO] No hubo cambios en .py, Waitress sigue corriendo. >> %LOG%
)

:fin
echo [%date% %time%] Auto-deploy completado. >> %LOG%
echo. >> %LOG%
endlocal
