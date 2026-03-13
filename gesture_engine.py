import cv2
import mediapipe as mp
import numpy as np
import os
import time
import urllib.request
import ctypes
import threading
from pycaw.pycaw import AudioUtilities
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

try:
    import screen_brightness_control as sbc
except ImportError:
    sbc = None

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

# Store the model in the user's home directory so it persists across runs
# perfectly even when packaged as an executable!
DATA_DIR = os.path.expanduser("~/.gesture_control")
os.makedirs(DATA_DIR, exist_ok=True)
MODEL_PATH = os.path.join(DATA_DIR, "hand_landmarker.task")
PINCH_MIN = 20.0
PINCH_MAX = 200.0
MIN_AUDIBLE_SCALAR = 0.12
SMOOTHING = 0.25
BRIGHTNESS_MIN = 0
BRIGHTNESS_MAX = 100
BRIGHTNESS_MIN_SPAN = 35.0
BRIGHTNESS_CALIB_MARGIN = 6.0
THUMB_DIR_THRESHOLD = 0.08
MEDIA_COOLDOWN_SEC = 1.0

VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002

def ensure_model(path: str) -> None:
    if os.path.exists(path):
        return
    print("Downloading hand landmarker model...")
    urllib.request.urlretrieve(MODEL_URL, path)

def get_finger_states(hand_lms):
    thumb_open = abs(hand_lms[4].x - hand_lms[2].x) > 0.04
    index_open = hand_lms[8].y < hand_lms[6].y
    middle_open = hand_lms[12].y < hand_lms[10].y
    ring_open = hand_lms[16].y < hand_lms[14].y
    pinky_open = hand_lms[20].y < hand_lms[18].y
    states = [thumb_open, index_open, middle_open, ring_open, pinky_open]
    return states, sum(states)

def map_distance_to_scalar(length: float) -> float:
    norm = np.clip((length - PINCH_MIN) / (PINCH_MAX - PINCH_MIN), 0.0, 1.0)
    curved = norm ** 0.55
    return float(MIN_AUDIBLE_SCALAR + (1.0 - MIN_AUDIBLE_SCALAR) * curved)

def map_distance_to_brightness(length: float, pinch_min: float, pinch_max: float) -> int:
    span = max(BRIGHTNESS_MIN_SPAN, pinch_max - pinch_min)
    norm = np.clip((length - pinch_min) / span, 0.0, 1.0)
    curved = norm ** 0.8
    return int(np.clip(np.interp(curved, [0.0, 1.0], [BRIGHTNESS_MIN, BRIGHTNESS_MAX]), BRIGHTNESS_MIN, BRIGHTNESS_MAX))

def send_media_play_pause_key() -> None:
    ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP, 0)

class GestureEngine:
    def __init__(self):
        self.running = False
        self.latest_frame = None
        self.lock = threading.Lock()
        
        # State variables for UI
        self.ui_volume = 0
        self.ui_brightness = 0
        self.ui_muted = False
        self.ui_gestures = []
        
        # Audio setup
        devices = AudioUtilities.GetSpeakers()
        self.volume = devices.EndpointVolume
        self.is_muted = bool(self.volume.GetMute())
        self.current_scalar = float(self.volume.GetMasterVolumeLevelScalar())
        self.ui_volume = int(self.current_scalar * 100)
        self.ui_muted = self.is_muted
        
        # Brightness setup
        self.current_brightness = None
        if sbc is not None:
            try:
                val = sbc.get_brightness(display=0)
                if isinstance(val, list):
                    val = val[0]
                self.current_brightness = float(val)
                self.ui_brightness = int(self.current_brightness)
            except Exception:
                pass
                
        self.left_pinch_min = None
        self.left_pinch_max = None
        self.media_is_playing = None
        self.last_media_action_time = 0.0
        
        ensure_model(MODEL_PATH)
        base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=2,
            running_mode=vision.RunningMode.IMAGE,
        )
        self.hand_detector = vision.HandLandmarker.create_from_options(options)
        self.cap = None
        self.thread = None

    def start(self, camera_index=0):
        if self.running:
            return
        self.cap = cv2.VideoCapture(camera_index)
        self.running = True
        self.thread = threading.Thread(target=self._process_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join()
        if self.cap is not None:
            self.cap.release()
        self.latest_frame = None

    def _set_brightness_safe(self, value: int) -> bool:
        if sbc is None:
            return False
        try:
            sbc.set_brightness(int(np.clip(value, BRIGHTNESS_MIN, BRIGHTNESS_MAX)), display=0)
            return True
        except Exception:
            return False

    def _process_loop(self):
        while self.running:
            success, img = self.cap.read()
            if not success:
                time.sleep(0.01)
                continue

            imgRGB = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=imgRGB)
            results = self.hand_detector.detect(mp_image)
            gesture_texts = []
            
            # Refresh system volume state occasionally (in case changed externally)
            try:
                self.is_muted = bool(self.volume.GetMute())
                self.ui_muted = self.is_muted
            except: pass

            if results.hand_landmarks:
                for hand_idx, handLms in enumerate(results.hand_landmarks):
                    lmList = []
                    h, w, c = img.shape
                    for id, lm in enumerate(handLms):
                        cx, cy = int(lm.x*w), int(lm.y*h)
                        lmList.append((id, cx, cy))

                    finger_states, open_count = get_finger_states(handLms)
                    thumb_open, index_open, middle_open, ring_open, pinky_open = finger_states

                    hand_label = "Unknown"
                    if results.handedness and hand_idx < len(results.handedness) and results.handedness[hand_idx]:
                        hand_label = results.handedness[hand_idx][0].category_name

                    if hand_label == "Right":
                        thumb_delta_y = handLms[2].y - handLms[4].y
                        other_fingers_closed = not index_open and not middle_open and not ring_open and not pinky_open
                        now = time.time()

                        if other_fingers_closed and thumb_delta_y > THUMB_DIR_THRESHOLD:
                            if self.media_is_playing is not True and (now - self.last_media_action_time) >= MEDIA_COOLDOWN_SEC:
                                send_media_play_pause_key()
                                self.media_is_playing = True
                                self.last_media_action_time = now
                            gesture_texts.append("Right: Thumb Up -> Play")

                        elif other_fingers_closed and thumb_delta_y < -THUMB_DIR_THRESHOLD:
                            if self.media_is_playing is not False and (now - self.last_media_action_time) >= MEDIA_COOLDOWN_SEC:
                                send_media_play_pause_key()
                                self.media_is_playing = False
                                self.last_media_action_time = now
                            gesture_texts.append("Right: Thumb Down -> Pause")

                        elif open_count == 0:
                            if not self.is_muted:
                                self.volume.SetMute(1, None)
                                self.is_muted = True
                                self.ui_muted = True
                            gesture_texts.append("Right: Fist -> Muted")
                        elif open_count == 5:
                            if self.is_muted:
                                self.volume.SetMute(0, None)
                                self.is_muted = False
                                self.ui_muted = False
                            gesture_texts.append("Right: Open Hand -> Unmuted")
                        elif thumb_open and index_open and not middle_open and not ring_open and not pinky_open and lmList:
                            x1, y1 = lmList[4][1], lmList[4][2]
                            x2, y2 = lmList[8][1], lmList[8][2]
                            length = np.hypot(x2-x1, y2-y1)

                            target_scalar = map_distance_to_scalar(length)
                            self.current_scalar = (1.0 - SMOOTHING) * self.current_scalar + SMOOTHING * target_scalar
                            self.volume.SetMasterVolumeLevelScalar(float(self.current_scalar), None)
                            if self.is_muted:
                                self.volume.SetMute(0, None)
                                self.is_muted = False
                                self.ui_muted = False
                            
                            vol_pct = int(self.current_scalar * 100)
                            self.ui_volume = vol_pct
                            gesture_texts.append(f"Right: Volume {vol_pct}%")

                            cv2.circle(img,(x1,y1),10,(255,0,0),cv2.FILLED)
                            cv2.circle(img,(x2,y2),10,(255,0,0),cv2.FILLED)
                            cv2.line(img,(x1,y1),(x2,y2),(255,0,0),3)
                        else:
                            gesture_texts.append(f"Right: Open fingers {open_count}")

                    elif hand_label == "Left":
                        if thumb_open and index_open and not middle_open and not ring_open and not pinky_open and lmList:
                            x1, y1 = lmList[4][1], lmList[4][2]
                            x2, y2 = lmList[8][1], lmList[8][2]
                            length = np.hypot(x2-x1, y2-y1)

                            if self.left_pinch_min is None or self.left_pinch_max is None:
                                self.left_pinch_min = length
                                self.left_pinch_max = length
                            else:
                                self.left_pinch_min = min(self.left_pinch_min, length)
                                self.left_pinch_max = max(self.left_pinch_max, length)

                            calibrated_min = self.left_pinch_min - BRIGHTNESS_CALIB_MARGIN
                            calibrated_max = self.left_pinch_max + BRIGHTNESS_CALIB_MARGIN
                            target_brightness = map_distance_to_brightness(length, calibrated_min, calibrated_max)

                            if self.current_brightness is None:
                                self.current_brightness = float(target_brightness)
                            else:
                                self.current_brightness = (1.0 - SMOOTHING) * self.current_brightness + SMOOTHING * target_brightness

                            if target_brightness <= 2:
                                self.current_brightness = 0.0

                            applied = self._set_brightness_safe(int(self.current_brightness))
                            bright_pct = int(self.current_brightness)
                            if applied:
                                self.ui_brightness = bright_pct
                                gesture_texts.append(f"Left: Brightness {bright_pct}%")
                            else:
                                gesture_texts.append("Left: Brightness control unavailable")

                            cv2.circle(img,(x1,y1),10,(0,165,255),cv2.FILLED)
                            cv2.circle(img,(x2,y2),10,(0,165,255),cv2.FILLED)
                            cv2.line(img,(x1,y1),(x2,y2),(0,165,255),3)
                        else:
                            gesture_texts.append(f"Left: Open fingers {open_count}")
                    else:
                        gesture_texts.append(f"{hand_label}: Open fingers {open_count}")

                    for lm in handLms:
                        px, py = int(lm.x * w), int(lm.y * h)
                        cv2.circle(img, (px, py), 3, (0, 255, 0), cv2.FILLED)

            with self.lock:
                self.ui_gestures = gesture_texts
                # Convert BGR to RGB for tkinter display
                self.latest_frame = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    def get_state(self):
        with self.lock:
            return {
                "frame": self.latest_frame,
                "volume": self.ui_volume,
                "brightness": self.ui_brightness,
                "muted": self.ui_muted,
                "gestures": self.ui_gestures
            }
