"""Shared tone adjustment for import previews and unedited JPG copies."""

import math

from PIL import Image, ImageOps


AUTO_BRIGHTNESS_TARGET_MEDIAN = 118
AUTO_BRIGHTNESS_MIN_GAMMA = 0.80
MAX_EXTRA_BRIGHTNESS = 0.25


def extra_brightness_amount(level: int) -> float:
    """Map the UI's 0–100 lift control to a conservative RGB offset."""
    if not 0 <= level <= 100:
        raise ValueError("Brightness must be between 0 and 100.")
    return level * MAX_EXTRA_BRIGHTNESS / 100


def auto_brightness_gamma(image: Image.Image) -> float:
    """Lift dark midtones without moving black or white points."""
    preview = image.convert("RGB")
    preview.thumbnail((256, 256))
    histogram = ImageOps.grayscale(preview).histogram()
    midpoint = (preview.width * preview.height + 1) // 2
    cumulative = 0
    median = 0
    for value, count in enumerate(histogram):
        cumulative += count
        if cumulative >= midpoint:
            median = value
            break

    if median <= 3 or median >= AUTO_BRIGHTNESS_TARGET_MEDIAN:
        return 1.0
    target = AUTO_BRIGHTNESS_TARGET_MEDIAN / 255
    measured = median / 255
    return max(AUTO_BRIGHTNESS_MIN_GAMMA, math.log(target) / math.log(measured))


def brighten(image: Image.Image, level: int = 0) -> Image.Image:
    """Apply the automatic tone curve and optional user-selected lift."""
    offset = extra_brightness_amount(level)
    gamma = auto_brightness_gamma(image)
    if gamma == 1.0 and offset == 0:
        return image

    pixels = image if image.mode in {"RGB", "L"} else image.convert("RGB")
    tone_curve = [
        min(255, round(255 * (value / 255) ** gamma + 255 * offset))
        for value in range(256)
    ]
    return pixels.point(tone_curve * len(pixels.getbands()))
