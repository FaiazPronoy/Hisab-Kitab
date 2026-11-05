"""Only used when a raw OCR pass comes back with low confidence. Each step
runs only if the image needs it; nothing is binarized wholesale."""
import cv2
import numpy as np
from PIL import Image

MIN_SHORT_SIDE = 1400


def deskew_angle(gray: np.ndarray) -> float:
    thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    pts = cv2.findNonZero(thr)
    if pts is None or len(pts) < 500:
        return 0.0
    angle = cv2.minAreaRect(pts)[-1]
    if angle > 45:
        angle -= 90
    return float(angle) if 0.3 < abs(angle) < 10 else 0.0


def preprocess(img: Image.Image) -> tuple[Image.Image, list[str]]:
    steps = []
    gray = np.array(img.convert("L"))
    steps.append("grayscale")

    short = min(gray.shape)
    if short < MIN_SHORT_SIDE:
        scale = MIN_SHORT_SIDE / short
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        steps.append("upscale")

    angle = deskew_angle(gray)
    if angle:
        h, w = gray.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        gray = cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)
        steps.append(f"deskew:{angle:.1f}")

    if gray.std() < 45:
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        steps.append("clahe")

    noise = cv2.Laplacian(gray, cv2.CV_64F).var()
    if noise > 1500:
        gray = cv2.fastNlMeansDenoising(gray, h=7)
        steps.append("denoise")

    return Image.fromarray(gray), steps
