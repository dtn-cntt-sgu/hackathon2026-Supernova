# Benchmark audit

Audit reference: commit `d80b15c6e25b753ac0ea1e34222d99ed42d47131`, 2026-11-08. This document audits historical claims; freshly generated `reports/hackathon-benchmark/` results are the measurement record. Model manifest approval labels are metadata, not independent accuracy validation.

| Evidence | Classification | Finding |
|---|---|---|
| Vehicle ONNX artifact | VERIFIED | Local SHA-256 equals manifest: `25fb82c0bec3091c099f359e66398a03cc73ee8917dc85467c44fad6115e81d7`. Production is HCMC VGG16-SSD, classes motorcycle/car/bus/truck, adaptive tiling and class-aware NMS; it is not YOLO26. Matching hash proves artifact identity, not accuracy. |
| Flood ONNX artifact | VERIFIED | Local SHA-256 equals manifest: `ea537875c78762a22261af663997e0d98b724f03c063698286fa02d161198496`. Actual runtime status and timing must be measured separately. |
| Flood dataset generator | EXISTING | `prepare_flood_dataset.py` generates entirely procedural images/masks, seed 42, default train400/val80/test80. No photographed HCMC scene is read. All splits share scene grammar/textures; random splitting does not establish field generalization. Group flags (night/wet/flood) are not persisted. |
| Independent labelled flood/vehicle data | BLOCKED | `data/datasets/` is absent in this checkout. Camera snapshots have no verified masks/boxes and are not labelled test data. No new accuracy number can be calculated from them. |
| Historical flood IoU .7059, F1 .8276 | NOT VERIFIED | Stored in manifest/docs, no available test corpus/result rows to reproduce. Legacy `evaluate_checkpoint` pooled pixels (global IoU) but printed “Mean IoU”; it did not compute mean per-image IoU. Corrected labels and added explicit per-image output; old aliases remain for exporter compatibility. |
| Historical Rain/Night PASS | NOT VERIFIED | Legacy evaluator printed PASS unconditionally, with no subgroup measurements. Removed unconditional PASS. Missing group labels now yield NOT EVALUATED. Exporter no longer invents reviewed=true or latency18.5. Existing model manifest is deliberately unchanged. |
| Checkpoint vs deployment | BLOCKED | PyTorch is absent in the current local environment. Legacy checkpoint evaluation uses full images; production flood inference blacks out top25% before model input, then masks output and evaluates road ROI. Legacy accuracy must not be presented as deployment accuracy. |
| `benchmark_yolo26_hcmc.py` | EXISTING / NOT VERIFIED | Historical filename/docs say YOLO26, but constructor loads current VGG16-SSD. Compares single-frame vs tiled detection counts and average latency on first25 local frames. No GT, AP, recall, warmup distribution, or independence evidence. More detections do not prove greater accuracy. |
| `benchmark_flood_inference.py` | EXISTING | Synthetic tensor model-only timing. Cannot establish image accuracy or camera end-to-end throughput. Read actual new performance results for current provider, warmup, iterations, timing scope. |
| `benchmark_vision.py` | EXISTING | Uses actual inference and checks model schema/hash, but historical small iteration counts were insufficient for robust p99/three-run claims. Separate new harness records scope and metadata. |
| `FLOOD_MODEL_TRAINING.md` | NOT VERIFIED | Historical “Mean IoU”, Rain/Night PASS, 125.5FPS and p95=9.50ms lack current reproducible labelled data/raw timing evidence. Manifest p95=18.5ms conflicts with document9.50ms. Neither is a newly measured result. |
| `CORE_CAMERA_AND_PERFORMANCE_ACCEPTANCE.md` | NOT VERIFIED | Historical 58–60FPS, 100/106 CoreML nodes, ANE/Metal assignment and speedup are not established by provider availability alone. 170 probes of796 do not prove completed whole-network sweep. Old Enhanced tab statements are obsolete. |
| Landing/sweep/load scripts | EXISTING | `benchmark_landing.js`, `measure_camera_sweep.py`, `k6_route_search.js` require their stated browser/backend/network environment. Script existence is not evidence of current execution. New runner distinguishes local test scenarios from field safety/ETA accuracy and forbids external load tests by default. |

No production weights/configuration were changed by this audit. No synthetic test result is presented as real traffic accuracy. Original model training corpus, camera grouping and external vehicle licence/training claims in the manifest remain unverified unless separately provided. Content and camera leakage checks cover only references explicitly supplied in an evaluation manifest; they do not prove absence of leakage against an unavailable original corpus.

The new evaluator refuses missing provenance, malformed labels, duplicate images (file and decoded-pixel hash), test/train or test/val content overlap and shared camera groups. Human or synthetic annotation declarations scope measurements; they are not independently certified. Ground truth must use the original image coordinate system. Flood pixel metrics evaluate only production ROI. Vehicle AP uses production-filtered predictions and a documented 101-point interpolation protocol; it is not official COCO AP with area/crowd/maxDet settings.

## Additional legacy operational limitations

- `measure_camera_sweep.py` imports `process_all_cameras_vision`, which is no longer exported by the current vision module. Its `await get_redis_client()` call also differs from the current synchronous factory. It treats every non-new result as deduplicated even on failure, and its full-fleet target is a hardcoded projection `(796/14)*10`, not a measured completed sweep. It is not used by the new runner; do not cite its target600s flag as acceptance evidence.
- `benchmark_landing.js` hardcodes a Microsoft Edge executable on macOS and reports a UI-specific historical label; it is not portable to Windows and does not measure AI or backend throughput. New dashboard rendering checks are Playwright contract tests, not a replacement claim about browser FPS.
- The previous k6 configuration included arbitrary p95 thresholds. The bounded benchmark now has no latency SLA unless explicitly supplied with `K6_P95_LIMIT_MS`; errors remain a stop condition. Local bursts use one request per VU, not a sustained production load.

## Current collector audit changes

The benchmark load target now enforces loopback-only TCP/DNS in its own temporary process. Disabling workers alone did not prevent cache-miss news fetches in route handling; the original diagnostic run is retained separately and must not be described as fully egress-isolated. This guard does not modify production configuration or fabricate replacement evidence.

Provider/camera endpoint timestamps distinguish retrieval from capture. Metadata counters may disagree because they have different definitions and update windows; the camera report preserves original counts instead of normalizing them into “live” success. A whole-network scheduler target flag is not a measured complete sweep.

The first regression/load checks overlapped on this memory-constrained host and caused connection timeouts/OSRM pressure. Those attempts remain diagnostic logs; accepted regression must be run sequentially after load. No timeout is converted to success, and no production timeout limit is changed to pass the benchmark.
