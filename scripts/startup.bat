@echo off
REM ============================================================
REM  startup.bat — Arranca SME y abre Chrome en monitor secundario
REM
REM  Para autoarranque con Windows (elige una opcion):
REM    1. Acceso directo en la carpeta de inicio:
REM       Ejecuta en el Explorador:  shell:startup
REM       Pega aqui un acceso directo a este .bat
REM    2. Tarea programada:
REM       taskschd.msc -> Nueva tarea -> Trigger: "Al iniciar sesion"
REM       Accion: iniciar programa -> este .bat
REM ============================================================

SETLOCAL

REM --- Rutas --------------------------------------------------
SET "PROJECT_DIR=%~dp0.."
SET "VENV_PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"

REM --- Servidor -----------------------------------------------
SET "PORT=5050"
SET "THREADS=4"
SET "APP_MODULE=app:app"

REM --- Monitor secundario -------------------------------------
REM  MONITOR_X: coordenada X donde empieza el monitor secundario.
REM  Monitor primario de 1920px de ancho -> secundario en X=1920.
REM  Ajusta este valor segun tu configuracion de pantallas.
SET "MONITOR_X=1920"
SET "MONITOR_Y=0"

REM --- Chrome (busca en rutas comunes si no esta en PATH) -----
SET "CHROME=chrome"
IF EXIST "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    SET "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
)
IF EXIST "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    SET "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

REM ==========================================================
REM  1. Iniciar waitress en segundo plano (ventana minimizada)
REM ==========================================================
ECHO [SME] Iniciando servidor en localhost:%PORT%...
START "SME-Flask" /MIN /D "%PROJECT_DIR%" "%VENV_PYTHON%" -m waitress --listen=0.0.0.0:%PORT% --threads=%THREADS% %APP_MODULE%

REM ==========================================================
REM  2. Esperar a que el servidor responda (polling cada 1s)
REM ==========================================================
ECHO [SME] Esperando respuesta...
:WAIT_LOOP
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://localhost:%PORT%' -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
    IF ERRORLEVEL 1 (
        TIMEOUT /T 1 /NOBREAK >nul
        GOTO WAIT_LOOP
    )

REM ==========================================================
REM  3. Abrir Chrome maximizado en monitor secundario
REM ==========================================================
ECHO [SME] Abriendo navegador...
START "" "%CHROME%" --new-window --window-position=%MONITOR_X%,%MONITOR_Y% --start-maximized "http://localhost:%PORT%"

ECHO [SME] Listo.
ENDLOCAL
