"""
posture_ai.py – AI posture detection (runs on the Raspberry Pi 5).

The USB webcam (Logitech C270) looks at the person from the SIDE, at shoulder
height. Once per second (AI_FRAME_INTERVAL_S) the newest frame goes through
the YOLO11n-pose model (course lesson 8c), which finds 17 body keypoints.
From the ear and the shoulder on the side facing the camera we calculate the
neck angle:

        ear  o                 angle = how far the ear is IN FRONT of the
            /                          shoulder, in degrees from vertical
           /  angle                    0°  = ear straight above the shoulder
          /___|                        25° = head pushed forward ("tech neck")
    shoulder  o

    angle > BAD_POSTURE_ANGLE (25°)  -> "bad"
    angle < GOOD_POSTURE_ANGLE (22°) -> "good" again (in between: unchanged)
    no person / ear or shoulder not visible -> "none"

"In front" is decided with the nose: it is always on the side the person
faces, so the angle is correct whether they face left or right in the image.
The median of the last POSTURE_SMOOTHING angles is used, so one odd frame
does not flip the result.

Every check is published on desk/posture as JSON:
    {"state": "good", "angle": 14.2}      ("none" -> "angle": null)
desk_controller.py turns it into the RGB LED colour, the OLED line and a
warning after 10 s of bad posture.

Model: the first run downloads yolo11n-pose.pt (6 MB) into models/ and
exports it to NCNN (models/yolo11n-pose_ncnn_model), the format that runs
fastest on the Pi 5 CPU, as in the course. Later runs load the NCNN model
directly (about 0.1–0.2 s per frame).

Multithreading: a camera thread reads frames non-stop and keeps only the
newest one. A webcam buffers a few frames; reading only once per second would
otherwise give a picture from the past.

Privacy: frames are only processed in memory. Nothing is saved or sent,
only the result (state + angle).

Usage (from the repository root):
    python pi/posture_ai.py                  run, publish desk/posture
    python pi/posture_ai.py --show           same + preview window with skeleton
                                             and angle (needs the Pi desktop/VNC)
    python pi/posture_ai.py --image a.jpg    test photos without camera or MQTT,
                                             e.g. the side-profile photos for the
                                             scale model (add --show to see them)
    python pi/posture_ai.py --camera 1       other camera than CAMERA_INDEX
Stop with Ctrl+C (or q in the preview window).
"""

import argparse
import json
import math
import os
import statistics
import sys
import threading
import time
from collections import deque

import config

L = config.Limits
T = config.Topics

# COCO keypoint numbers used by YOLO pose
NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR, LEFT_SHOULDER, RIGHT_SHOULDER = 0, 1, 2, 3, 4, 5, 6
SIDES = {"left": (LEFT_EAR, LEFT_SHOULDER, LEFT_EYE), "right": (RIGHT_EAR, RIGHT_SHOULDER, RIGHT_EYE)}

WINDOW = "Smart Desk posture (q = quit)"


# ---------------------------------------------------------------------------
# Posture maths (no AI, no hardware: easy to test)
# ---------------------------------------------------------------------------
def neck_angle(points, conf, min_conf=config.KEYPOINT_MIN_CONF):
    """Neck angle in degrees from 17 keypoints, or None if it cannot be measured.

    points -- list of 17 (x, y) pixel positions (y grows downwards)
    conf   -- list of 17 confidences (0–1)
    Returns (angle, side): side is "left"/"right", the body side seen by the camera.
    """
    # The side facing the camera has the most confident ear + shoulder
    side = max(SIDES, key=lambda s: min(conf[SIDES[s][0]], conf[SIDES[s][1]]))
    ear_i, shoulder_i, eye_i = SIDES[side]
    if min(conf[ear_i], conf[shoulder_i]) < min_conf:
        return None
    (ex, ey), (sx, sy) = points[ear_i], points[shoulder_i]

    # Which way does the person face? The nose (or else the eye) is in front of the ear.
    face = NOSE if conf[NOSE] >= min_conf else eye_i if conf[eye_i] >= min_conf else None
    if face is not None and abs(points[face][0] - ex) > 1:
        forward = 1 if points[face][0] > ex else -1
        dx = (ex - sx) * forward            # > 0: ear in front of the shoulder
    else:
        dx = abs(ex - sx)                   # direction unknown: assume forward
    dy = sy - ey                            # > 0: ear above the shoulder
    return math.degrees(math.atan2(dx, dy)), side


def classify(angle, previous):
    """good/bad with hysteresis: above BAD -> bad, below GOOD -> good, in between unchanged."""
    if angle > L.BAD_POSTURE_ANGLE:
        return "bad"
    if angle < L.GOOD_POSTURE_ANGLE:
        return "good"
    return previous if previous in ("good", "bad") else "good"


class PostureFilter:
    """Median over the last few angles + hysteresis; 'none' clears the history."""

    def __init__(self, size=config.POSTURE_SMOOTHING):
        """Start with no history."""
        self.angles = deque(maxlen=size)
        self.state = "none"

    def update(self, angle):
        """Feed one measured angle (or None = nobody); returns (state, smoothed angle)."""
        if angle is None:
            self.angles.clear()
            self.state = "none"
            return self.state, None
        self.angles.append(angle)
        smooth = statistics.median(self.angles)
        self.state = classify(smooth, self.state)
        return self.state, smooth


# ---------------------------------------------------------------------------
# Camera thread
# ---------------------------------------------------------------------------
class Camera:
    """Reads the webcam in a thread of its own and keeps only the newest frame."""

    def __init__(self, source, width, height):
        """Open the camera (index like 0, or a video file for testing) and start reading."""
        import cv2

        self.cv2 = cv2
        self.source = source
        self.is_file = isinstance(source, str)
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open camera {source!r} – check: v4l2-ctl --list-devices")
        if not self.is_file:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.size = (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self._frame = None
        self._frame_time = 0.0
        self._lock = threading.Lock()          # protects _frame and _frame_time
        self._stop = threading.Event()
        self.ended = False                     # a test video reached its end
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def _run(self):
        """Thread body: grab frames as fast as the camera delivers them."""
        failures = 0
        while not self._stop.is_set():
            ok, frame = self.cap.read()
            if not ok:
                if self.is_file:
                    self.ended = True
                    return
                failures += 1
                if failures == 50:              # about 2 s without a frame
                    print("[camera] no frames – is the webcam still plugged in?")
                time.sleep(0.05)
                continue
            failures = 0
            with self._lock:
                self._frame, self._frame_time = frame, time.monotonic()
            if self.is_file:
                time.sleep(1 / self.fps)        # play a test video at its real speed

    def latest(self, max_age=2.0):
        """The newest frame, or None if there is none from the last max_age seconds."""
        with self._lock:
            if self._frame is None or time.monotonic() - self._frame_time > max_age:
                return None
            return self._frame

    def close(self):
        """Stop the thread and release the camera."""
        self._stop.set()
        self._thread.join(2)
        self.cap.release()


# ---------------------------------------------------------------------------
# AI model
# ---------------------------------------------------------------------------
def load_model():
    """Load the NCNN pose model; download and export it first if it is not there yet."""
    import logging

    from ultralytics import YOLO

    logging.getLogger("ultralytics").setLevel(logging.ERROR)   # quiet, as in lesson 8c
    config.MODEL_DIR.mkdir(exist_ok=True)
    ncnn_dir = config.MODEL_DIR / f"{config.POSE_MODEL}_ncnn_model"
    if not ncnn_dir.exists():
        pt_file = config.MODEL_DIR / f"{config.POSE_MODEL}.pt"
        print(f"First run: downloading {pt_file.name} and exporting it to NCNN (takes a minute) ...")
        YOLO(str(pt_file)).export(format="ncnn")
        print(f"Model ready: {ncnn_dir}")
    return YOLO(str(ncnn_dir), task="pose")


class PostureDetector:
    """YOLO pose on one frame -> neck angle of the main person."""

    def __init__(self):
        """Load the model (slow the first time)."""
        self.model = load_model()

    def detect(self, frame):
        """Returns (angle or None, details): details has the keypoints for drawing."""
        from ultralytics.engine.results import Results

        result = next(iter(self.model.predict(frame, verbose=False)))   # one frame in, one result out
        assert isinstance(result, Results)
        details = {"result": result, "points": None, "side": None}
        kp = result.keypoints
        if result.boxes is None or len(result.boxes) == 0 or kp is None or kp.conf is None:
            return None, details
        # The person at the desk is the biggest one in the picture
        areas = (result.boxes.xywh[:, 2] * result.boxes.xywh[:, 3]).tolist()
        i = areas.index(max(areas))
        points = kp.xy[i].tolist()
        conf = kp.conf[i].tolist()
        details["points"] = points
        measured = neck_angle(points, conf)
        if measured is None:
            return None, details
        angle, details["side"] = measured
        return angle, details


def draw(frame, details, state, angle):
    """Preview image: YOLO skeleton + ear-shoulder line + state and angle (only for --show)."""
    import cv2

    result = details["result"]
    image = result.plot(boxes=False) if result is not None else frame.copy()
    colour = {"good": (0, 200, 0), "bad": (0, 0, 255)}.get(state, (200, 200, 200))
    if details["points"] and details["side"]:
        ear_i, shoulder_i, _ = SIDES[details["side"]]
        ear = tuple(int(v) for v in details["points"][ear_i])
        shoulder = tuple(int(v) for v in details["points"][shoulder_i])
        cv2.line(image, shoulder, ear, colour, 4)
        cv2.line(image, shoulder, (shoulder[0], max(0, shoulder[1] - 120)), (255, 255, 255), 1)
    text = f"{state.upper()}" + (f"  {angle:.0f} deg" if angle is not None else "")
    cv2.rectangle(image, (0, 0), (260, 44), (0, 0, 0), -1)
    cv2.putText(image, text, (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 2)
    return image


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------
def check_images(paths, show):
    """--image: run the model on photos and print the result; nothing is published."""
    import cv2

    detector = PostureDetector()
    for path in paths:
        frame = cv2.imread(path)
        if frame is None:
            print(f"{path}: cannot read the image")
            continue
        angle, details = detector.detect(frame)
        state = "none" if angle is None else classify(angle, None)
        print(f"{path}: {state}" + (f", neck angle {angle:.1f}° ({details['side']} side to the camera)"
                                    if angle is not None else " (no ear + shoulder found)"))
        if show:
            cv2.imshow(WINDOW, draw(frame, details, state, angle))
            print("  press a key for the next photo")
            cv2.waitKey(0)
    if show:
        cv2.destroyAllWindows()


def run(camera_source, show):
    """Main program: camera thread + one posture check per AI_FRAME_INTERVAL_S, published on MQTT."""
    import paho.mqtt.client as mqtt
    from paho.mqtt.enums import CallbackAPIVersion

    cv2 = None
    if show:
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")   # as in lesson 8c
        import cv2
        if not os.environ.get("DISPLAY"):
            print("--show needs a screen: run it in a terminal on the Pi desktop or over VNC, not plain SSH")
            show = False

    print("Loading the pose model ...")
    detector = PostureDetector()
    camera = Camera(camera_source, config.CAMERA_WIDTH, config.CAMERA_HEIGHT)
    print(f"Camera {camera_source!r} open at {camera.size[0]}x{camera.size[1]}")

    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="smartdesk-posture-ai")
    client.on_connect = lambda c, u, f, rc, p: print(
        f"[mqtt] connected to {config.MQTT_HOST}:{config.MQTT_PORT}" if not rc.is_failure
        else f"[mqtt] connection refused: {rc}")
    client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
    client.loop_start()

    posture = PostureFilter()
    print(f"Publishing {T.POSTURE} every {config.AI_FRAME_INTERVAL_S} s "
          f"(bad above {L.BAD_POSTURE_ANGLE}°, good below {L.GOOD_POSTURE_ANGLE}°). Ctrl+C to stop.")
    next_check = time.monotonic()
    waited_since = None
    try:
        while not camera.ended:
            now = time.monotonic()
            if now < next_check:
                if show and cv2 is not None and cv2.waitKey(20) & 0xFF == ord("q"):
                    break
                time.sleep(0.01)
                continue
            next_check = max(next_check + config.AI_FRAME_INTERVAL_S, now)

            frame = camera.latest()
            if frame is None:
                waited_since = waited_since or now
                if now - waited_since > 5:
                    print("[camera] no frame for 5 s – posture unknown")
                    waited_since = now
                continue
            waited_since = None

            start = time.monotonic()
            angle, details = detector.detect(frame)
            state, smooth = posture.update(angle)
            ms = (time.monotonic() - start) * 1000
            client.publish(T.POSTURE, json.dumps(
                {"state": state, "angle": None if smooth is None else round(smooth, 1)}))
            print(f"  {state:<4}" + (f" {smooth:5.1f}°" if smooth is not None else "       ")
                  + f"   ({ms:.0f} ms)")
            if show and cv2 is not None:
                cv2.imshow(WINDOW, draw(frame, details, state, smooth))
    except KeyboardInterrupt:
        print("\nStopping ...")
    finally:
        camera.close()
        client.loop_stop()
        client.disconnect()
        if show and cv2 is not None:
            cv2.destroyAllWindows()


def main():
    """Parse the command line and start."""
    parser = argparse.ArgumentParser(description="Smart Desk posture detection (YOLO pose)")
    parser.add_argument("--show", action="store_true", help="preview window with skeleton and angle")
    parser.add_argument("--image", nargs="+", metavar="PHOTO", help="test photos instead of the camera")
    parser.add_argument("--camera", default=str(config.CAMERA_INDEX),
                        help="camera index (default from config.py) or a video file")
    args = parser.parse_args()

    if args.image:
        check_images(args.image, args.show)
        return
    source = int(args.camera) if args.camera.isdigit() else args.camera
    try:
        run(source, args.show)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
