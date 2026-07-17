@echo off
cd /d "C:\Users\artur\sme-motel"
call venv\Scripts\activate
venv\Scripts\python.exe -c "import sqlite3; c = sqlite3.connect('database/sme.db'); c.execute('UPDATE configuracion SET valor = ? WHERE clave = ?', ('empleado', 'modo_actual')); c.commit(); print('Modo reseteado a empleado')"
start /min cmd /c "waitress-serve --call --host=0.0.0.0 --port=5050 app:create_app"
timeout /t 3 /nobreak > nul
start chrome --kiosk --app=http://localhost:5050
exit