"""Hand-computed fixtures validate metric code, never field accuracy."""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scripts.benchmark_eval.datasets import load_dataset, write_template
from scripts.benchmark_eval.evaluation import evaluate_flood, evaluate_vehicle
from scripts.benchmark_eval.metrics import aggregate_segmentation, binary_counts, detection_metrics, segmentation_metrics


def test_binary_hand_computed_and_undefined():
    counts = binary_counts([[1, 1], [0, 0]], [[1, 0], [1, 0]])
    assert counts == dict(tp=1, fp=1, fn=1, tn=1)
    values = segmentation_metrics(counts)
    assert values["global_iou"] == pytest.approx(1 / 3)
    assert values["dice_f1"] == 0.5
    empty = segmentation_metrics(binary_counts([[0]], [[0]]))
    assert empty["global_iou"] is None
    assert empty["false_positive_rate"] == 0
    assert aggregate_segmentation([])["status"] == "NOT EVALUATED"
    with pytest.raises(ValueError):
        binary_counts([[1]], [[1]], [[0]])


def test_global_differs_from_per_image():
    values = aggregate_segmentation([segmentation_metrics(dict(tp=1, fp=0, fn=0, tn=0)),
                                    segmentation_metrics(dict(tp=0, fp=9, fn=0, tn=0))])
    assert values["global_iou"] == .1
    assert values["mean_iou_per_image"] == .5


def test_detection_ap_matching_duplicates_and_missing():
    gt = [{"image_id": "a", "class": "car", "bbox": [0, 0, 10, 10]}]
    pred = [{**gt[0], "score": .9}, {**gt[0], "score": .8}]
    result = detection_metrics(pred, gt)
    assert result["map50"] == result["map50_95"] == 1
    assert result["tp"] == 1 and result["fp"] == 1 and result["fn"] == 0
    assert result["precision"] == .5
    assert result["per_class"]["truck"]["ap50"] is None
    assert detection_metrics([], gt)["map50"] == 0
    assert detection_metrics([], [])["map50"] is None


def test_detection_wrong_class_and_iou_sweep():
    truth = {"image_id": "a", "class": "car", "bbox": [0, 0, 10, 10]}
    result = detection_metrics([{**truth, "class": "truck", "score": .9}], [truth])
    assert result["fp"] == result["fn"] == 1
    assert result["confusion_matrix"][1][3] == 1
    result = detection_metrics([{**truth, "bbox": [0, 0, 7, 10], "score": .9}], [truth])
    assert result["map50"] == 1
    assert result["map50_95"] == .5


def manifest(tmp_path, task="flood"):
    image = np.random.default_rng(7).integers(0, 255, (100, 100, 3), dtype=np.uint8)
    Image.fromarray(image).save(tmp_path / "image.png")
    Image.fromarray(np.zeros((100, 100), dtype=np.uint8)).save(tmp_path / "mask.png")
    record = {"id": "fixture", "split": "test", "image": "image.png", "mask": "mask.png", "groups": ["dry"], "boxes": []}
    data = dict(dataset_id="unit-fixture", task=task, source="Generated unit fixture, not camera data", license="Test only",
                annotation_type="synthetic", annotation_source="Hand-specified negative fixture", records=[record])
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    return path, data


def test_manifest_requires_provenance_and_binary_masks(tmp_path):
    path, data = manifest(tmp_path)
    _, audit = load_dataset(path, "flood")
    assert audit["public_examples_authorized"] is False
    assert audit["annotation_type"] == "synthetic"
    Image.fromarray(np.full((100, 100), 128, dtype=np.uint8)).save(tmp_path / "mask.png")
    with pytest.raises(ValueError, match="Mask"):
        load_dataset(path, "flood")
    del data["license"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="license"):
        load_dataset(path, "flood")


def test_content_and_camera_leakage_rejected(tmp_path):
    path, data = manifest(tmp_path)
    data["records"].append({"id": "train", "split": "train", "image": "image.png"})
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Content leakage"):
        load_dataset(path, "flood")
    Image.fromarray(np.ones((100, 100, 3), dtype=np.uint8)).save(tmp_path / "other.png")
    data["records"][1]["image"] = "other.png"
    for record in data["records"]:
        record["camera_id"] = "same-camera"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Camera grouping leakage"):
        load_dataset(path, "flood")


def test_vehicle_invalid_box_rejected(tmp_path):
    path, data = manifest(tmp_path, "vehicle")
    data["records"][0]["boxes"] = [{"class": "car", "bbox": [0, 0, 101, 10]}]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="outside"):
        load_dataset(path, "vehicle")


def test_unlabelled_does_not_invent_accuracy_or_keep_old_examples(tmp_path):
    (tmp_path / "flood_examples.png").write_bytes(b"old private example")
    for evaluator, task in [(evaluate_flood, "flood"), (evaluate_vehicle, "vehicle")]:
        result = evaluator(tmp_path)
        assert result["status"] == "NOT EVALUATED"
        assert "metrics" not in result
        assert result["model"]["hash_matches_manifest"]
        assert json.loads((tmp_path / f"{task}_metrics.json").read_text())["status"] == "NOT EVALUATED"
    assert not (tmp_path / "flood_examples.png").exists()


def test_template_has_no_fabricated_labels(tmp_path):
    path = tmp_path / "template.json"
    write_template(path, "flood")
    data = json.loads(path.read_text())
    assert data["records"] == [] and data["allow_public_examples"] is False
    with pytest.raises(ValueError, match="No labelled"):
        load_dataset(path, "flood")


def test_deployment_flood_integration_roi_and_private_artifacts(tmp_path):
    pytest.importorskip("onnxruntime")
    path, data = manifest(tmp_path)
    # Synthetic fixture: positive GT exists ONLY above road ROI. It is not field GT.
    truth = np.zeros((100, 100), dtype=np.uint8)
    truth[:25] = 255
    Image.fromarray(truth).save(tmp_path / "mask.png")
    result = evaluate_flood(tmp_path / "results", path)
    assert result["status"] == "LIMITED", result
    metrics = result["metrics"]
    assert metrics["tp"] == metrics["fn"] == 0
    assert metrics["tn"] + metrics["fp"] == 7500
    assert result["groups"]["rain"]["status"] == "NOT EVALUATED"
    assert (tmp_path / "results/flood_predictions.csv").exists()
    assert (tmp_path / "results/flood_confusion_matrix.png").exists()
    assert not (tmp_path / "results/flood_examples.png").exists()
    # Only generated artificial test images are authorized here.
    data["allow_public_examples"] = True
    path.write_text(json.dumps(data))
    result = evaluate_flood(tmp_path / "results", path)
    assert result["status"] == "LIMITED"
    with Image.open(tmp_path / "results/flood_examples.png") as panels:
        assert panels.width == 1024


def test_deployment_vehicle_integration_no_accuracy_from_negative_fixture(tmp_path):
    pytest.importorskip("onnxruntime")
    path, _ = manifest(tmp_path, "vehicle")
    result = evaluate_vehicle(tmp_path / "results", path, compare_baseline=True)
    assert result["status"] == "LIMITED", result
    assert result["metrics"]["map50"] is None  # negative-only data cannot measure recall/AP
    assert result["metrics"]["classes_with_ground_truth"] == 0
    assert result["baseline"]["metrics"]["map50"] is None
    assert not (tmp_path / "results/vehicle_examples.png").exists()


def test_invalid_manifest_error_does_not_publish_private_path_or_credentials(tmp_path):
    path, data = manifest(tmp_path)
    secret = "private-user-sensitive-token"
    data["records"][0]["image"] = f"/Users/{secret}/camera.png"
    path.write_text(json.dumps(data))
    result = evaluate_flood(tmp_path / "results", path)
    public_json = (tmp_path / "results/flood_metrics.json").read_text()
    assert result["status"] == "NOT EVALUATED"
    assert "ValueError" in result["reason"]
    assert secret not in public_json and "/Users/" not in public_json
    assert "camera.png" not in public_json
