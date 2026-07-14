# watchdog.ps1 — Revive waitress si se cayó (lo corre la tarea 'SME Watchdog' cada 5 min).
# Señal de "está vivo": algo escuchando en el puerto 5050. Si no, arranca waitress.
# NO resetea el modo ni abre Chrome: es solo la red de seguridad del servidor.

$ErrorActionPreference = 'SilentlyContinue'
$dir = 'C:\Users\artur\sme-motel'
$log = Join-Path $env:TEMP 'sme_watchdog.log'

$listening = Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction SilentlyContinue
if ($listening) { exit 0 }   # ya hay quien sirva; nada que hacer

# Puerto muerto -> levantar waitress igual que start.bat (mismo comando, sin kiosco)
$exe = Join-Path $dir 'venv\Scripts\waitress-serve.exe'
Start-Process -FilePath $exe `
    -ArgumentList '--call', '--host=0.0.0.0', '--port=5050', 'app:create_app' `
    -WorkingDirectory $dir -WindowStyle Hidden

"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  waitress estaba caído -> reiniciado" |
    Out-File -FilePath $log -Append -Encoding utf8
