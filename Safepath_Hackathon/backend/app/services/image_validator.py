"""
Camera Snapshot Image Validator for SafePathAI.
Validates raw byte payloads using magic byte verification, Pillow decoding,
perceptual hash matching for server placeholders, dark frame detection,
and duplicate frame tracking.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import io
import logging
import os
from typing import Optional, Set, Tuple
import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Known placeholder hashes from HCMC port 8007 ("IMAGE NOT AVAILABLE" / server error frame)
KNOWN_PLACEHOLDER_MD5 = {
    "5f5b2bf141af555a87e3f1d6c3ab3017",  # Standard 306x236 PNG placeholder
    "9653ea117b2c39d4c477b0949f95860e",  # Standard 290x183 PNG placeholder (5,192 bytes)
    "d681aeeeaa468b620624b02e3b7c82d4",  # Enhanced 290x183 JPEG placeholder (9,556 bytes)
    "e1618a5bfd7eb9698d287bc1283a0fc3",  # Legacy 290x183 PNG placeholder (5,192 bytes)
    "2de90420a3a7e9bb8506b00be846dc8c",  # Standard 290x183 test placeholder
}
KNOWN_PLACEHOLDER_SHA256 = {
    "fd47eb800054605740ae3032c114ae934c618a23ff9b72839d97e3fc91da84ba",
    "44246c5dfb69d91cffde872630d789488bf0e603ceda9c53b1984185aec4ffba",
}
KNOWN_PLACEHOLDER_DHASHES = {
    "0x310f9e860e473303",  # Raw 290x183 placeholder
    "0x310e9e868e063305",  # Enhanced 290x183 placeholder
}

# Load normalized 64x64 template for robust invariant detection
_TEMPLATE_FILE = os.path.join(os.path.dirname(__file__), "placeholder_template.bin")
_PLACEHOLDER_TEMPLATE_64: Optional[np.ndarray] = None
if os.path.exists(_TEMPLATE_FILE):
    try:
        with open(_TEMPLATE_FILE, "rb") as _tf:
            _PLACEHOLDER_TEMPLATE_64 = np.frombuffer(_tf.read(), dtype=np.uint8).reshape((64, 64))
    except Exception as _e:
        logger.debug("Could not load placeholder template: %s", _e)


class ImageValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID_MAGIC_BYTES = "INVALID_MAGIC_BYTES"
    CORRUPTED_PAYLOAD = "CORRUPTED_PAYLOAD"
    PLACEHOLDER_ERROR_FRAME = "PLACEHOLDER_ERROR_FRAME"
    DARK_NO_SIGNAL_FRAME = "DARK_NO_SIGNAL_FRAME"
    BLANK_LOW_VARIANCE_FRAME = "BLANK_LOW_VARIANCE_FRAME"
    DUPLICATE_FRAME = "DUPLICATE_FRAME"
    DIMENSIONS_TOO_SMALL = "DIMENSIONS_TOO_SMALL"
    DIMENSIONS_TOO_LARGE = "DIMENSIONS_TOO_LARGE"


@dataclass
class ImageValidationResult:
    """Detailed outcome of validating a camera snapshot image payload."""
    status: ImageValidationStatus
    is_valid: bool
    format: Optional[str]
    width: Optional[int]
    height: Optional[int]
    file_size_bytes: int
    md5_hash: str
    dhash: Optional[str]
    mean_intensity: Optional[float]
    captured_at: Optional[datetime]
    capture_time_status: str  # "VERIFIED_TIMESTAMP" or "CAPTURE_TIME_UNKNOWN"
    retrieved_at: datetime
    error_message: Optional[str] = None


def compute_dhash(image: Image.Image, hash_size: int = 8) -> str:
    """
    Computes difference hash (dHash) for an image.
    Resizes to (hash_size + 1, hash_size), converts to grayscale,
    and compares adjacent pixels.
    """
    resized = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = np.array(resized)
    # Difference between consecutive columns
    diff = pixels[:, 1:] > pixels[:, :-1]
    return hex(int("".join("1" if b else "0" for b in diff.flatten()), 2))


def hamming_distance(hex1: str, hex2: str) -> int:
    """Computes bitwise Hamming distance between two hex hash strings."""
    try:
        val1 = int(hex1, 16)
        val2 = int(hex2, 16)
        return bin(val1 ^ val2).count("1")
    except (ValueError, TypeError):
        return 999


def check_template_correlation(image_bytes: bytes) -> tuple[bool, float]:
    """
    Computes normalized cross-correlation of image against the 64x64 placeholder template.
    Returns (is_match, correlation_score).
    """
    if _PLACEHOLDER_TEMPLATE_64 is None or not image_bytes:
        return False, 0.0
    try:
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return False, 0.0
        norm_64 = cv2.resize(img, (64, 64))
        corr = float(cv2.matchTemplate(norm_64, _PLACEHOLDER_TEMPLATE_64, cv2.TM_CCOEFF_NORMED)[0][0])
        return corr >= 0.85, corr
    except Exception:
        return False, 0.0


def validate_camera_image_bytes(
    image_bytes: bytes,
    previous_md5: Optional[str] = None,
    previous_sha256: Optional[str] = None,
    previous_dhash: Optional[str] = None,
    min_width: int = 100,
    min_height: int = 100,
    min_mean_intensity: float = 8.0,
    min_std_dev: float = 3.0,
    max_dhash_drift_for_dup: int = 1,
    max_pixels: int = 16_777_216,
) -> ImageValidationResult:
    """
    Rigorous multi-stage validation of incoming camera snapshot bytes:
    1. Magic bytes check (JPEG, PNG, WebP).
    2. Payload integrity and Pillow decoding.
    3. Dimension checks.
    4. Exact MD5 / SHA256 against known server error placeholders.
    5. Dark frame / no-signal detection (low mean intensity).
    6. Blank / low-variance frame detection (low standard deviation).
    7. Duplicate frame detection against previous capture.
    8. Strict separation of retrieved_at vs captured_at.
    """
    retrieved_at = datetime.now(timezone.utc)
    file_size = len(image_bytes)

    # 1. Magic bytes check
    is_jpeg = image_bytes.startswith(b"\xff\xd8\xff") or image_bytes.startswith(b"\xff\xd8")
    is_png = image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    is_webp = image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]

    if not (is_jpeg or is_png or is_webp):
        md5 = hashlib.md5(image_bytes).hexdigest()
        return ImageValidationResult(
            status=ImageValidationStatus.INVALID_MAGIC_BYTES,
            is_valid=False,
            format=None,
            width=None,
            height=None,
            file_size_bytes=file_size,
            md5_hash=md5,
            dhash=None,
            mean_intensity=None,
            captured_at=None,
            capture_time_status="CAPTURE_TIME_UNKNOWN",
            retrieved_at=retrieved_at,
            error_message="Payload does not match JPEG, PNG, or WebP magic bytes",
        )

    # 2. Check known placeholder hashes
    md5 = hashlib.md5(image_bytes).hexdigest()
    sha256 = hashlib.sha256(image_bytes).hexdigest()
    if md5 in KNOWN_PLACEHOLDER_MD5 or sha256 in KNOWN_PLACEHOLDER_SHA256:
        return ImageValidationResult(
            status=ImageValidationStatus.PLACEHOLDER_ERROR_FRAME,
            is_valid=False,
            format="PNG",
            width=306,
            height=236,
            file_size_bytes=file_size,
            md5_hash=md5,
            dhash=None,
            mean_intensity=None,
            captured_at=None,
            capture_time_status="CAPTURE_TIME_UNKNOWN",
            retrieved_at=retrieved_at,
            error_message="Server returned standard 'IMAGE NOT AVAILABLE' placeholder frame",
        )

    # 3. Decode image with Pillow
    try:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        if width * height > max_pixels:
            return ImageValidationResult(
                status=ImageValidationStatus.DIMENSIONS_TOO_LARGE, is_valid=False,
                format=img.format, width=width, height=height, file_size_bytes=file_size,
                md5_hash=md5, dhash=None, mean_intensity=None, captured_at=None,
                capture_time_status="CAPTURE_TIME_UNKNOWN", retrieved_at=retrieved_at,
                error_message="Decoded image exceeds camera pixel budget",
            )
        img.verify()  # Verify structural integrity
        # Re-open for pixel reading after verify()
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        img_format = img.format
    except Exception as exc:
        return ImageValidationResult(
            status=ImageValidationStatus.CORRUPTED_PAYLOAD,
            is_valid=False,
            format=None,
            width=None,
            height=None,
            file_size_bytes=file_size,
            md5_hash=md5,
            dhash=None,
            mean_intensity=None,
            captured_at=None,
            capture_time_status="CAPTURE_TIME_UNKNOWN",
            retrieved_at=retrieved_at,
            error_message=f"Pillow decode error: {exc}",
        )

    # 4. Dimension check
    if width < min_width or height < min_height:
        return ImageValidationResult(
            status=ImageValidationStatus.DIMENSIONS_TOO_SMALL,
            is_valid=False,
            format=img_format,
            width=width,
            height=height,
            file_size_bytes=file_size,
            md5_hash=md5,
            dhash=None,
            mean_intensity=None,
            captured_at=None,
            capture_time_status="CAPTURE_TIME_UNKNOWN",
            retrieved_at=retrieved_at,
            error_message=f"Image dimensions ({width}x{height}) below minimum {min_width}x{min_height}",
        )

    # 5. Convert to RGB numpy array for photometric analysis
    rgb_img = img.convert("RGB")
    np_arr = np.array(rgb_img, dtype=np.float32)
    mean_val = float(np.mean(np_arr))
    std_val = float(np.std(np_arr))

    # 6. Dark / no-signal check
    if mean_val < min_mean_intensity:
        return ImageValidationResult(
            status=ImageValidationStatus.DARK_NO_SIGNAL_FRAME,
            is_valid=False,
            format=img_format,
            width=width,
            height=height,
            file_size_bytes=file_size,
            md5_hash=md5,
            dhash=None,
            mean_intensity=mean_val,
            captured_at=None,
            capture_time_status="CAPTURE_TIME_UNKNOWN",
            retrieved_at=retrieved_at,
            error_message=f"Image is nearly black/no-signal (mean intensity {mean_val:.2f} < {min_mean_intensity})",
        )

    # 7. Blank / low-variance check
    if std_val < min_std_dev:
        return ImageValidationResult(
            status=ImageValidationStatus.BLANK_LOW_VARIANCE_FRAME,
            is_valid=False,
            format=img_format,
            width=width,
            height=height,
            file_size_bytes=file_size,
            md5_hash=md5,
            dhash=None,
            mean_intensity=mean_val,
            captured_at=None,
            capture_time_status="CAPTURE_TIME_UNKNOWN",
            retrieved_at=retrieved_at,
            error_message=f"Image is uniform/uninformative (standard deviation {std_val:.2f} < {min_std_dev})",
        )

    # 8. Compute difference hash (dHash)
    curr_dhash = compute_dhash(img)

    # 8a. Perceptual dHash check against confirmed server placeholder variants
    for p_dhash in KNOWN_PLACEHOLDER_DHASHES:
        dist = hamming_distance(curr_dhash, p_dhash)
        if dist <= 3:
            return ImageValidationResult(
                status=ImageValidationStatus.PLACEHOLDER_ERROR_FRAME,
                is_valid=False,
                format=img_format,
                width=width,
                height=height,
                file_size_bytes=file_size,
                md5_hash=md5,
                dhash=curr_dhash,
                mean_intensity=mean_val,
                captured_at=None,
                capture_time_status="CAPTURE_TIME_UNKNOWN",
                retrieved_at=retrieved_at,
                error_message=f"Perceptual dHash match ({dist} bits) with known placeholder frame",
            )

    # 8b. Structural normalized template cross-correlation check
    if _PLACEHOLDER_TEMPLATE_64 is not None:
        try:
            gray_cv = cv2.cvtColor(np_arr.astype(np.uint8), cv2.COLOR_RGB2GRAY)
            norm_64 = cv2.resize(gray_cv, (64, 64))
            corr = float(cv2.matchTemplate(norm_64, _PLACEHOLDER_TEMPLATE_64, cv2.TM_CCOEFF_NORMED)[0][0])
            if corr >= 0.85:
                return ImageValidationResult(
                    status=ImageValidationStatus.PLACEHOLDER_ERROR_FRAME,
                    is_valid=False,
                    format=img_format,
                    width=width,
                    height=height,
                    file_size_bytes=file_size,
                    md5_hash=md5,
                    dhash=curr_dhash,
                    mean_intensity=mean_val,
                    captured_at=None,
                    capture_time_status="CAPTURE_TIME_UNKNOWN",
                    retrieved_at=retrieved_at,
                    error_message=f"Template correlation {corr:.3f} indicates 'IMAGE NOT AVAILABLE' placeholder",
                )
        except Exception as exc:
            logger.debug("Template matching check failed: %s", exc)

    # 8c. Discrete graphic check (synthetic 23-color grayscale icon detection)
    if width <= 360 and height <= 260:
        colors = img.getcolors(maxcolors=40)
        if colors is not None and len(colors) <= 30:
            diff_rg = float(np.max(np.abs(np_arr[:, :, 0] - np_arr[:, :, 1])))
            diff_gb = float(np.max(np.abs(np_arr[:, :, 1] - np_arr[:, :, 2])))
            if diff_rg < 2.0 and diff_gb < 2.0 and std_val > 40:
                return ImageValidationResult(
                    status=ImageValidationStatus.PLACEHOLDER_ERROR_FRAME,
                    is_valid=False,
                    format=img_format,
                    width=width,
                    height=height,
                    file_size_bytes=file_size,
                    md5_hash=md5,
                    dhash=curr_dhash,
                    mean_intensity=mean_val,
                    captured_at=None,
                    capture_time_status="CAPTURE_TIME_UNKNOWN",
                    retrieved_at=retrieved_at,
                    error_message=f"Image contains only {len(colors)} discrete grayscale levels (synthetic placeholder graphic)",
                )

    # 9. Duplicate detection (Exact SHA256 / MD5 / perceptual dHash match)
    if (previous_sha256 and sha256 == previous_sha256) or (previous_md5 and md5 == previous_md5):
        return ImageValidationResult(
            status=ImageValidationStatus.DUPLICATE_FRAME,
            is_valid=False,
            format=img_format,
            width=width,
            height=height,
            file_size_bytes=file_size,
            md5_hash=md5,
            dhash=curr_dhash,
            mean_intensity=mean_val,
            captured_at=None,
            capture_time_status="CAPTURE_TIME_UNKNOWN",
            retrieved_at=retrieved_at,
            error_message="Identical SHA256/MD5 to previous snapshot (frozen/duplicate camera stream)",
        )

    if previous_dhash:
        dist = hamming_distance(curr_dhash, previous_dhash)
        if dist <= max_dhash_drift_for_dup:
            return ImageValidationResult(
                status=ImageValidationStatus.DUPLICATE_FRAME,
                is_valid=False,
                format=img_format,
                width=width,
                height=height,
                file_size_bytes=file_size,
                md5_hash=md5,
                dhash=curr_dhash,
                mean_intensity=mean_val,
                captured_at=None,
                capture_time_status="CAPTURE_TIME_UNKNOWN",
                retrieved_at=retrieved_at,
                error_message=f"Perceptual dHash distance {dist} indicates frozen/duplicate frame",
            )

    # All validation stages passed!
    return ImageValidationResult(
        status=ImageValidationStatus.VALID,
        is_valid=True,
        format=img_format,
        width=width,
        height=height,
        file_size_bytes=file_size,
        md5_hash=md5,
        dhash=curr_dhash,
        mean_intensity=mean_val,
        captured_at=None,  # Unless OCR overlay or provider header verified
        capture_time_status="CAPTURE_TIME_UNKNOWN",
        retrieved_at=retrieved_at,
        error_message=None,
    )

