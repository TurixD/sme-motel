@echo off
cd /d "C:\Users\artur\sme-motel"
call venv\Scripts\activate
start /min cmd /c "python app.py"
timeout /t 3 /nobreak > nul
start chrome --kiosk --app=http://localhost:5050
exit