' watchdog_hidden.vbs — corre el watchdog de waitress SIN ventana visible.
' wscript.exe no tiene consola, y Run(...,0,...) lanza PowerShell oculto desde
' el inicio, así que no aparece la pantalla negra que parpadeaba cada 5 min.
CreateObject("WScript.Shell").Run _
  "powershell -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\artur\sme-motel\scripts\watchdog.ps1""", _
  0, False
