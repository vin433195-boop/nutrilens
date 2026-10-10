@echo off
rem Sao lưu CSDL NutriLens. Đặt lịch chạy hằng ngày lúc 2 giờ sáng bằng lệnh (chạy một lần trong cmd):
rem   schtasks /Create /SC DAILY /ST 02:00 /TN "NutriLens backup" /TR "D:\HOC\Python_Web_MonAN\deploy\backup_windows.bat"
cd /d "%~dp0.."
python -m flask --app app backup-db >> logs\backup.log 2>&1
