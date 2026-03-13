@echo off
echo Cleaning old builds...
rmdir /s /q build
rmdir /s /q dist

echo Compiling Gesture Control App...
pyinstaller --noconfirm --onedir --windowed --name "GestureControl" --add-data "C:/Users/eshwa/AppData/Local/Programs/Python/Python313/Lib/site-packages/customtkinter;customtkinter/" --collect-all mediapipe gui_app.py

echo Done!
echo To share the app, just ZIP the entire 'dist\GestureControl' folder!
pause
