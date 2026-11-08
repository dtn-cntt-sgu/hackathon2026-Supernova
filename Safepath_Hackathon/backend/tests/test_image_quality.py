"""Original-frame quality and preprocessing tests; synthetic images are unit-only."""
import cv2
import numpy as np
import pytest
from backend.app.services.vision import assess_image_quality, preprocess_camera_image


def test_quality_flags_preserve_low_light_and_blur():
    assessment=assess_image_quality(np.full((240,320,3),15,dtype=np.uint8))
    assert assessment.quality_metrics.is_low_light
    assert "LOW_LIGHT" in assessment.quality_flags
    assert assessment.quality_metrics.is_blurry


def test_quality_empty_input_rejected():
    with pytest.raises(ValueError): assess_image_quality(np.zeros((0,0,3),dtype=np.uint8))


def test_preprocessing_keeps_original_pixels_and_only_masks_roi(tmp_path):
    image=np.random.default_rng(17).integers(20,235,(240,320,3),dtype=np.uint8)
    path=tmp_path/"unit-original.png"
    cv2.imwrite(str(path),image)
    before=path.read_bytes()
    result=preprocess_camera_image(str(path))
    assert np.array_equal(result.original_image,image)
    assert np.array_equal(result.roi_image[60:],image[60:])
    assert not result.roi_image[:60].any()
    assert path.read_bytes()==before
    assert not hasattr(result,"enhanced_image")
