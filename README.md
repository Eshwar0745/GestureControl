# 👋 Gesture Control Dashboard

A modern, standalone Windows desktop application that lets you completely control your system's volume, brightness, and media playback using secure, local AI hand tracking.

Built with Python, **MediaPipe Tasks**, **OpenCV**, and **CustomTkinter**. No data is ever sent to the cloud. Fast, lightweight, and deployable as a `.zip`.

![Interface Preview](https://via.placeholder.com/800x450.png?text=Gesture+Control+Dashboard+Screenshot+Here)

---

## ⚡ Features & Controls

The app tracks both hands simultaneously.

**🤚 Right Hand (Audio & Media)**
- 🤏 **Pinch (Thumb + Index distance):** Adjust System Volume smoothly.
- ✊ **Fist:** Mute System Volume.
- 🖐️ **Open Palm (all 5 fingers):** Unmute System Volume.
- 👍 **Thumb Up (other fingers closed):** Play Media.
- 👎 **Thumb Down (other fingers closed):** Pause Media.

**🤚 Left Hand (Display Controls)**
- 🤏 **Pinch (Thumb + Index distance):** Adjust Screen Brightness smoothly. 
  *(Tip: Upon opening the app, extend your left thumb and index fully once to automatically calibrate the maximum brightness range to your current camera distance).*

---

## 🚀 How to Run (Pre-built Executable)

If you downloaded the pre-compiled release:
1. Extract the `.zip` file completely.
2. Go into the extracted folder.
3. Double-click `GestureControl.exe`.
4. Allow camera permissions if prompted. The UI will pop up instantly!

> **Note:** The very first time you boot the software, it may take 2-3 seconds as it acquires the lightweight `hand_landmarker.task` model to `~/.gesture_control/`.

---

## 💻 How to Run (From Source)

If you are a developer looking to edit the Python files or re-build the local environment:

### Prerequisites:
Make sure you have **Python 3.10+** installed on Windows.

### 1. Install Dependencies
```bash
pip install opencv-python mediapipe numpy pycaw screen-brightness-control customtkinter Pillow
```

### 2. Run the App
```bash
python gui_app.py
```

### 3. Build & Package (Creating an .EXE)
To generate the redistributable executable folder in Windows:
```bash
pip install pyinstaller
.\build.bat
```
The deployable application folder will be placed in `dist/GestureControl`. You can zip this folder to share it with anyone!

---

## 🔧 Architecture / Technical details
* **`gesture_engine.py`:** Handles real-time background threading for the OpenCV loop. Connects MediaPipe's Task Vision API hand landmarks to `pycaw` (Windows Audio) and `ctypes` (Win32 Keyboard Events).
* **`gui_app.py`:** The main layout utilizing `CustomTkinter` to present an aesthetic dark-mode dashboard without locking up or dropping camera frames.
* Models are fetched explicitly and cached in the user's home directory avoiding the nightmare of bundling massive TF-Lite models deep inside PyInstaller's hidden temp environments.

## 📝 License
Feel free to fork, clone, and build upon this!
