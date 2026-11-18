"""Step 3b: decide where to crop each aspect ratio, centred on the speaker's face when one is found."""
import statistics

import cv2


def face_center(video_path: str, start: float, end: float, samples: int = 12) -> tuple[float, float] | None:
    """Median (x, y) of the largest face across sampled frames, as 0..1 fractions; None if no face."""
    if not hasattr(cv2, "CascadeClassifier"):
        return None  # no detector in this OpenCV build: centre crop
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    xs, ys = [], []
    try:
        for i in range(samples):
            t = start + (end - start) * (i + 0.5) / samples
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            scale = 640 / max(w, h)
            small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1 else frame
            gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(30, 30))
            if len(faces):
                fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                sh, sw = gray.shape
                xs.append((fx + fw / 2) / sw)
                ys.append((fy + fh / 2) / sh)
    finally:
        cap.release()
    if len(xs) < max(2, samples // 4):
        return None
    return statistics.median(xs), statistics.median(ys)


CORNERS = {"top-left": (0, 0), "top-right": (1, 0), "bottom-left": (0, 1), "bottom-right": (1, 1)}


def corner_box(src_w: int, src_h: int, corner: str, aspect: float, width_frac: float = 0.28) -> tuple[int, int, int, int]:
    """A facecam-sized box in one corner of the frame, with the top panel's aspect. Returns (w, h, x, y)."""
    w = int(src_w * width_frac) // 2 * 2
    h = min(src_h, int(w / aspect)) // 2 * 2
    fx, fy = CORNERS.get(corner, (1, 0))
    return w, h, (src_w - w) * fx, (src_h - h) * fy


def find_facecam(video_path: str, start: float, end: float, aspect: float, samples: int = 16) -> tuple[int, int, int, int] | None:
    """Look for a webcam overlay: a face that stays put in a corner of the frame across the clip.
    Returns a crop box (w, h, x, y) in source pixels around it, or None."""
    if not hasattr(cv2, "CascadeClassifier"):
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    hits = []
    src_w = src_h = 0
    try:
        for i in range(samples):
            cap.set(cv2.CAP_PROP_POS_MSEC, (start + (end - start) * (i + 0.5) / samples) * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            src_h, src_w = frame.shape[:2]
            scale = 960 / src_w
            small = cv2.resize(frame, (960, int(src_h * scale)))
            gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(24, 24))
            sh, sw = gray.shape
            # only faces in the outer corners count (gameplay characters wander, a webcam doesn't)
            corner_faces = [f for f in faces
                            if (f[0] + f[2] / 2 < sw * 0.33 or f[0] + f[2] / 2 > sw * 0.67)
                            and (f[1] + f[3] / 2 < sh * 0.45 or f[1] + f[3] / 2 > sh * 0.55)]
            if corner_faces:
                fx, fy, fw, fh = max(corner_faces, key=lambda f: f[2] * f[3])
                hits.append(((fx + fw / 2) / sw, (fy + fh / 2) / sh, fw / sw))
    finally:
        cap.release()
    if len(hits) < max(3, samples // 3):
        return None
    xs, ys, ws = (sorted(v)[len(v) // 2] for v in zip(*hits))
    # the face must not move much: a webcam is fixed on screen
    if sum(abs(h[0] - xs) < 0.06 and abs(h[1] - ys) < 0.08 for h in hits) < len(hits) * 0.6:
        return None
    w = int(min(max(ws * 3.4, 0.16), 0.45) * src_w) // 2 * 2
    h = min(src_h, int(w / aspect)) // 2 * 2
    w = min(src_w, int(h * aspect)) // 2 * 2
    x = int(min(max(xs * src_w - w / 2, 0), src_w - w))
    y = int(min(max(ys * src_h - h * 0.45, 0), src_h - h))
    return w, h, x, y


def crop_box(src_w: int, src_h: int, out_w: int, out_h: int, center: tuple[float, float] | None) -> tuple[int, int, int, int]:
    """Largest crop of the source with the output aspect, positioned around center. Returns (w, h, x, y)."""
    target = out_w / out_h
    cx, cy = center if center else (0.5, 0.45)
    if src_w / src_h > target:  # source is wider: crop the sides
        h = src_h
        w = int(round(src_h * target / 2) * 2)
        x = int(min(max(cx * src_w - w / 2, 0), src_w - w))
        y = 0
    else:  # source is taller: crop top/bottom
        w = src_w
        h = int(round(src_w / target / 2) * 2)
        x = 0
        y = int(min(max(cy * src_h - h / 2, 0), src_h - h))
    return w, h, x, y
