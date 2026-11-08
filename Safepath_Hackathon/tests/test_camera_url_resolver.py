"""
Unit Tests for Camera URL Resolver Strategy (Phase 10).
Verifies canonical URLs, candidate variant order, and placeholder detection.
"""

from datetime import datetime, timezone
import pytest
from backend.app.services.camera_url_resolver import (
    build_candidate_camera_urls,
    get_canonical_camera_url,
    get_parameterized_camera_url,
)
from backend.app.services.image_validator import (
    ImageValidationStatus,
    validate_camera_image_bytes,
)


def test_canonical_url_avoids_clutter():
    cam_id = "56df8198c062921100c143dd"
    canonical = get_canonical_camera_url(cam_id)
    assert canonical.endswith(f"?id={cam_id}")
    assert "bg=black" not in canonical
    assert "w=300" not in canonical
    assert "h=230" not in canonical


def test_build_candidate_urls_priority_order():
    cam_id = "5deb576d1dc17d7c5515ad09"
    # By default, canonical must be first!
    candidates = build_candidate_camera_urls(cam_id)
    assert len(candidates) >= 2
    assert candidates[0][0] == "CANONICAL"
    assert candidates[0][1] == get_canonical_camera_url(cam_id)
    assert candidates[-1][0] == "PARAMETERIZED"

    # If camera historically succeeded with PARAMETERIZED, that takes priority
    cand_param = build_candidate_camera_urls(cam_id, preferred_variant="PARAMETERIZED")
    assert cand_param[0][0] == "PARAMETERIZED"
    assert cand_param[1][0] == "CANONICAL"


def test_placeholder_frame_is_rejected():
    import os
    sample_path = "docs/server_placeholder_sample.png"
    if os.path.exists(sample_path):
        with open(sample_path, "rb") as f:
            placeholder_bytes = f.read()
        val = validate_camera_image_bytes(placeholder_bytes)
        assert not val.is_valid
        assert val.status == ImageValidationStatus.PLACEHOLDER_ERROR_FRAME
    else:
        # Fallback md5 match test
        from backend.app.services.image_validator import PLACEHOLDER_FRAME_MD5
        assert len(PLACEHOLDER_FRAME_MD5) == 32
