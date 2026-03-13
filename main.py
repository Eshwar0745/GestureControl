import cv2
import mediapipe as mp
import numpy as np
import os
import time
import urllib.request
import ctypes
from pycaw.pycaw import AudioUtilities
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

try:
    import screen_brightness_control as sbc
except ImportError:
    sbc = None

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
MODEL_PATH = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")
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
    # Perceptual boost: makes lower distances less silent.
    curved = norm ** 0.55
    return float(MIN_AUDIBLE_SCALAR + (1.0 - MIN_AUDIBLE_SCALAR) * curved)


def map_distance_to_brightness(length: float, pinch_min: float, pinch_max: float) -> int:
    # Live calibration maps the user's real pinch range to 0-100.
    span = max(BRIGHTNESS_MIN_SPAN, pinch_max - pinch_min)
    norm = np.clip((length - pinch_min) / span, 0.0, 1.0)
    curved = norm ** 0.8
    return int(np.clip(np.interp(curved, [0.0, 1.0], [BRIGHTNESS_MIN, BRIGHTNESS_MAX]), BRIGHTNESS_MIN, BRIGHTNESS_MAX))


def get_current_brightness():
    if sbc is None:
        return None
    try:
        val = sbc.get_brightness(display=0)
        if isinstance(val, list):
            val = val[0]
        return float(val)
    except Exception:
        return None


def set_brightness_safe(value: int) -> bool:
    if sbc is None:
        return False
    try:
        sbc.set_brightness(int(np.clip(value, BRIGHTNESS_MIN, BRIGHTNESS_MAX)), display=0)
        return True
    except Exception:
        return False


def send_media_play_pause_key() -> None:
    ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP, 0)

# Volume control setup
devices = AudioUtilities.GetSpeakers()
volume = devices.EndpointVolume
is_muted = bool(volume.GetMute())
current_scalar = float(volume.GetMasterVolumeLevelScalar())
current_brightness = get_current_brightness()
left_pinch_min = None
left_pinch_max = None
media_is_playing = None
last_media_action_time = 0.0

ensure_model(MODEL_PATH)

base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
options = vision.HandLandmarkerOptions(
    base_options=base_options,
    num_hands=2,
    running_mode=vision.RunningMode.IMAGE,
)
hand_detector = vision.HandLandmarker.create_from_options(options)

cap = cv2.VideoCapture(0)

while True:

    success, img = cap.read()
    if not success:
        break

    imgRGB = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=imgRGB)

    results = hand_detector.detect(mp_image)
    gesture_texts = []

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
                # Right hand: gesture-first audio control flow.
                thumb_delta_y = handLms[2].y - handLms[4].y
                other_fingers_closed = not index_open and not middle_open and not ring_open and not pinky_open
                now = time.time()

                if other_fingers_closed and thumb_delta_y > THUMB_DIR_THRESHOLD:
                    if media_is_playing is not True and (now - last_media_action_time) >= MEDIA_COOLDOWN_SEC:
                        send_media_play_pause_key()
                        media_is_playing = True
                        last_media_action_time = now
                    gesture_texts.append("Right: Thumb Up -> Play")

                elif other_fingers_closed and thumb_delta_y < -THUMB_DIR_THRESHOLD:
                    if media_is_playing is not False and (now - last_media_action_time) >= MEDIA_COOLDOWN_SEC:
                        send_media_play_pause_key()
                        media_is_playing = False
                        last_media_action_time = now
                    gesture_texts.append("Right: Thumb Down -> Pause")

                elif open_count == 0:
                    if not is_muted:
                        volume.SetMute(1, None)
                        is_muted = True
                    gesture_texts.append("Right: Fist -> Muted")
                elif open_count == 5:
                    if is_muted:
                        volume.SetMute(0, None)
                        is_muted = False
                    gesture_texts.append("Right: Open Hand -> Unmuted")
                elif thumb_open and index_open and not middle_open and not ring_open and not pinky_open and lmList:
                    x1, y1 = lmList[4][1], lmList[4][2]
                    x2, y2 = lmList[8][1], lmList[8][2]
                    length = np.hypot(x2-x1, y2-y1)

                    target_scalar = map_distance_to_scalar(length)
                    current_scalar = (1.0 - SMOOTHING) * current_scalar + SMOOTHING * target_scalar
                    volume.SetMasterVolumeLevelScalar(float(current_scalar), None)
                    if is_muted:
                        volume.SetMute(0, None)
                        is_muted = False
                    gesture_texts.append(f"Right: Volume {int(current_scalar * 100)}%")

                    cv2.circle(img,(x1,y1),10,(255,0,0),cv2.FILLED)
                    cv2.circle(img,(x2,y2),10,(255,0,0),cv2.FILLED)
                    cv2.line(img,(x1,y1),(x2,y2),(255,0,0),3)
                else:
                    gesture_texts.append(f"Right: Open fingers {open_count}")

            elif hand_label == "Left":
                # Left hand: thumb+index controls brightness.
                if thumb_open and index_open and not middle_open and not ring_open and not pinky_open and lmList:
                    x1, y1 = lmList[4][1], lmList[4][2]
                    x2, y2 = lmList[8][1], lmList[8][2]
                    length = np.hypot(x2-x1, y2-y1)

                    if left_pinch_min is None or left_pinch_max is None:
                        left_pinch_min = length
                        left_pinch_max = length
                    else:
                        left_pinch_min = min(left_pinch_min, length)
                        left_pinch_max = max(left_pinch_max, length)

                    calibrated_min = left_pinch_min - BRIGHTNESS_CALIB_MARGIN
                    calibrated_max = left_pinch_max + BRIGHTNESS_CALIB_MARGIN
                    target_brightness = map_distance_to_brightness(length, calibrated_min, calibrated_max)

                    if current_brightness is None:
                        current_brightness = float(target_brightness)
                    else:
                        current_brightness = (1.0 - SMOOTHING) * current_brightness + SMOOTHING * target_brightness

                    if target_brightness <= 2:
                        current_brightness = 0.0

                    applied = set_brightness_safe(int(current_brightness))
                    if applied:
                        gesture_texts.append(f"Left: Brightness {int(current_brightness)}%")
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

    status_text = "Muted" if is_muted else "Unmuted"
    cv2.putText(img, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255) if is_muted else (0, 255, 0), 2)
    for i, txt in enumerate(gesture_texts):
        cv2.putText(img, txt, (10, 65 + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

    if sbc is None:
        cv2.putText(img, "Install screen_brightness_control for left-hand brightness", (10, 430), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
    cv2.imshow("Gesture Volume Control", img)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()
hand_detector.close()