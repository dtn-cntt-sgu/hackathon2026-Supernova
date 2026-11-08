# Prepare labelled evaluation data

No field accuracy is currently available: this checkout has no independently labelled test dataset. Do not generate procedural masks and call them human ground truth. Keep images private unless their owner explicitly permits publishing. `allow_public_examples` defaults to false; JSON/CSV/count/confusion outputs do not embed source images. Dataset manifests themselves should stay private because they may identify files/cameras.

Create an empty manifest (no model, training, dataset or network changes):

```sh
python -m scripts.benchmark_eval.datasets --task flood --output /private/dataset/flood.json
python -m scripts.benchmark_eval.datasets --task vehicle --output /private/dataset/vehicle.json
```

Use existing Python environment with repository runtime dependencies. Windows PowerShell supports the same Python commands; use Windows local paths. Fill provenance, records and labels manually. Example schema (illustrative paths only, not supplied labelled evidence):

```json
{
  "dataset_id": "independent-camera-review-v1",
  "task": "flood",
  "source": "Owner-permitted camera snapshots, acquisition dates and original source",
  "license": "Exact permission or dataset license; confirm evaluation rights",
  "annotation_type": "human",
  "annotation_source": "Annotator IDs, written rules, independent reviewer and dispute resolution",
  "allow_public_examples": false,
  "records": [
    {
      "id": "test-001",
      "split": "test",
      "image": "images/001.png",
      "mask": "masks/001.png",
      "camera_id": "camera-group-A",
      "groups": ["flooded", "rain", "night"]
    }
  ]
}
```

Paths are local and relative to manifest. Provide `source`, `license`, `annotation_source`, `annotation_type` (`human` or `synthetic`) and dataset ID. Empty records are refused. For vehicle task, replace mask with `"boxes": [{"class":"motorcycle","bbox":[10,20,40,60]}]`. Supported classes: motorcycle, car, bus, truck (model IDs1/2/3/4). Box coordinates are finite original-image pixels `[x1,y1,x2,y2]`, exclusive upper edges, positive area. `boxes: []` means an explicitly reviewed negative, not missing annotation. This small format does not support crowd/ignore/ambiguous boxes; adjudicate ambiguity before inclusion or exclude that image and document why.

For flood, label water using a local polygon/mask editor. Save a single-channel original-resolution binary PNG, background0 and water255 (1 is accepted). No resized/palette/RGB masks. Mask visible standing water, not rain streaks, wet-road sheen or streetlight reflections. Document uncertain/occluded pixels and exclude ambiguous images: this version has no ignore-pixel channel. Annotate the full image, retain the original; evaluation excludes top25% from both prediction and GT using actual production ROI. Flood IoU measures water segmentation, not depth, flood severity or a passable road.

Use groups `dry`, `wet`, `flooded`, `rain`, `night` only when a human/source annotation supports them; overlapping rain/night labels are allowed. Missing groups are NOT EVALUATED. Audit rain/night false positives independently, especially wet negative roads.

Split before annotation/model tuning by source camera, capture session, day and location. Avoid near-adjacent frames in different splits. Include known training and validation reference images as records with `split: train` or `val`; they need `id`, `image`, and `camera_id`, but no evaluation labels. The loader checks exact file hashes, decoded-pixel hashes and known camera overlaps. It cannot detect all near-duplicates nor compare to an unavailable original training corpus. Unknown independence is reported explicitly. Freeze a versioned manifest/hash before evaluating, record excluded samples, and never tune a threshold on the test split. Keep a held-out negative and positive sample distribution representative of intended use. Record annotator disagreement and per-group sample counts; small or synthetic results remain LIMITED.

Run actual deployment evaluation offline, with heuristic fallback disabled:

```sh
python -c "from pathlib import Path; from scripts.benchmark_eval.evaluation import evaluate_flood; evaluate_flood(Path('reports/hackathon-benchmark'), Path('/private/dataset/flood.json'))"
python -c "from pathlib import Path; from scripts.benchmark_eval.evaluation import evaluate_vehicle; evaluate_vehicle(Path('reports/hackathon-benchmark'), Path('/private/dataset/vehicle.json'), compare_baseline=True)"
```

The baseline is the SAME VGG16-SSD model, single-frame branch, same0.20 confidence and0.45 NMS settings; production enables adaptive tiling. Neither branch uses an OpenCV heuristic. Confidence floors remain production settings; AP is computed over retained predictions, so do not compare it directly with studies evaluating all raw confidence scores.

Flood: global IoU=`TP/(TP+FP+FN)` pools all ROI pixels; Dice=`2TP/(2TP+FP+FN)`, precision=`TP/(TP+FP)`, recall=`TP/(TP+FN)`. Mean per-image IoU averages defined image IoUs; empty-union images are counted and excluded, never silently assigned perfect accuracy. Zero denominators produce null. Confusion rows=true, columns=prediction. Pixel FP/FN and negative false-positive rate are reported separately.

Vehicle: score-ranked, same-class, one-to-one greedy box matching per image; AP interpolates precision at101 recall points. AP50 is IoU≥.50; AP50:95 averages10 IoU thresholds .50,.55,…,.95. Mean AP averages classes with GT only, reports that count, and leaves absent classes null. GT with no detections scores AP0. Fixed-threshold precision/recall/F1 use score≥.50 and IoU≥.50; FP and missed detections count class mistakes. The confusion matrix additionally matches class-agnostically to expose misclassification; background column=missed GT, background row=unmatched prediction. No true-negative count is defined for object detection. This is a documented lightweight AP protocol, not official COCO evaluation (no crowd, area bins or maxDet limits).

Outputs: `flood_metrics.json`, `flood_predictions.csv`, `flood_confusion_matrix.png`, and equivalent vehicle files. Public examples are written only when explicitly authorized by manifest; flood panels show Original|GT|Prediction|Errors, red FP/blue FN. Otherwise JSON records WITHHELD and source images are never copied. Reusing the same output directory removes prior example files to avoid accidental leakage. Unlabelled/invalid input produces status/reason without fabricated metrics. PyTorch parity is separately BLOCKED if torch is absent; ONNX execution does not prove checkpoint parity.
