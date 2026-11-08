# Benchmark implementation and local acceptance — 08/11/2026

Dashboard: http://localhost:3000/benchmark. Evidence is served from `frontend/public/benchmark/`, with original machine-readable results in `reports/hackathon-benchmark/`. No commit, push, merge, weight changes, production configuration changes or production deployment were performed.

## What actually ran

Base commit: `d80b15c6e25b753ac0ea1e34222d99ed42d47131`; benchmark tools and dashboard are uncommitted. A commit hash alone cannot reproduce this working tree. Environment JSON includes model hashes, measured environment and source-hash timing limitations. Final report formatting and safety fixes were applied after the measured inference run; those edits were not presented as new inference measurements.

Both ONNX hashes match the production manifest. Execution profiling observed CPUExecutionProvider, using two CPU threads. CoreML availability does not establish CoreML/ANE execution. Input: three valid private local camera snapshots, copied to immutable temporary files for measurement. This is a small latency sample, without independent accuracy labels or verified capture times. No camera images were published.

| Model | Model-only p95 across 3 sessions | Production pipeline-file p95 across 3 sessions |
|---|---:|---:|
| Production VGG16-SSD vehicle detector | 593.78–620.33 ms | 2598.18–3626.34 ms |
| FloodUNet ONNX | 11.19–11.50 ms | 16.68–18.95 ms |

Each model used 300 timed model-only calls and 60 file-pipeline calls across three independently constructed sessions, plus separate warmup. Pipeline includes file decoding/validation/quality/ROI and production inference/postprocessing, but excludes HTTP, queueing and overlay encoding. Model-only excludes image/tensor preprocessing. The report also records loading/cold/mean/std/percentiles, serial FPS, diagnostic stages and raw timings. ORT profiling adds overhead; 20 pipeline samples per session provide limited p99 precision. Peak process RSS was approximately 655 MiB; it is not model-exclusive memory.

- Routing: **52/52 specification scenarios pass**, including missing/stale/wrong-edge evidence, hazardous routes and provider failures. Labelled synthetic evidence tests constraints; it does not prove field AI accuracy. ETA error remains NOT EVALUATED without actual-trip ground truth.
- Camera: **796 registered**, **3/3 sampled originals valid**. List and summary status definitions disagree and are preserved with caveats. Readonly stored audit found 2301/2301 analyzed snapshot metadata hashes consistent; zero verified capture timestamps. Neither these counts nor retrieval age establish fleet uptime, capture age, sweep interval or byte-level overlay correctness.
- Load: **FAILED**. Final sequential local-only test: 1 VU succeeds at 1685.688 ms; 10 VUs have 100% five-second timeouts (p95 5000.611 ms). 25 VUs were stopped after failure; 50 VUs deferred. Backend process peak RSS approximately 157 MiB; CPU samples are lifetime-average process readings, excluding OSRM/database. These short bursts do not establish sustained production capacity.
- Flood/vehicle accuracy: **NOT EVALUATED** because no independent labelled test dataset exists here. No invented IoU/mAP, false confusion matrix or GT illustration was produced. Annotation manifest templates, validation, leakage checks and real production-path evaluation are implemented for future labelled data. PyTorch-vs-ONNX parity is BLOCKED without PyTorch and paired validation data.

Initial load attempts are retained: cold timeout, a guard startup bug, and a run overlapping regression. They are not isolated capacity acceptance. The final load was rerun sequentially with a corrected loopback-only socket/DNS guard. No third-party camera load test was performed.

## Commands and observed outcomes

Use the existing project virtual environment. Python is `python` after activation; this workstation uses `.venv/bin/python` explicitly.

| Command/scope | Result |
|---|---|
| `python scripts/run_hackathon_benchmark.py --quick --offline --output <temporary-output>` | Exit 0; ONNX measurements and unit scenarios; camera/load not network-accepted |
| `python scripts/run_hackathon_benchmark.py --full --qa-context <private-loopback-QA-context> --publish` | Exit 1; inference complete, load FAILED; failures intentionally preserved |
| `python -m pytest backend/tests -q --tb=short -rs` in isolated QA environment | **558 PASS, 15 SKIP**, 91.12 s; accepted sequential regression |
| Opt-in readonly OSRM/API/real-road live suites | **18 PASS**, 47.76 s |
| `python -m pytest backend/tests/test_benchmark_runner.py -q --tb=short` after final runner export changes | **14 PASS** |
| `npm run lint`, `npm run type-check`, `npm run test:unit` | PASS; **12 unit tests PASS** |
| `docker compose build frontend` | PASS; Next.js production build with `/benchmark` |
| Playwright actual-bundle desktop/mobile acceptance | **1 PASS**; real JSON, all 14 artifact URLs, hashes/statuses, no page errors or horizontal overflow |
| Dashboard UI contract fixtures | **4 PASS**, final combined browser run **5/5 PASS** (2.7 s). Four tests cover status handling, missing/invalid bundles, mobile layout and authorized image publication; fixtures are not benchmark metrics |
| Python compile, `git diff --check`, public JSON/redaction checks | PASS |
| Latest host Ruff invocation | NOT RUN: Ruff is not installed in the project virtual environment |

Fifteen default skips were 14 opt-in live cases plus one legacy PyTorch-dependent test. The live checks were separately enabled and passed. Earlier overlapping regression failed due to database connection timeouts; those logs were retained, not relabelled as a pass.

Local logs are under `/tmp/safepath-benchmark-*.log` and private output logs. They are not served publicly and may disappear on reboot. `commands.json` records section commands/exit codes; raw JSON/CSV retain measurement samples. Browser fixtures test UI behavior only. Build/runtime acceptance is local, not GitHub Actions or staging acceptance.

## Reproduce

From the repository root after environment setup:

```sh
python scripts/run_hackathon_benchmark.py --full --publish
```

Without a separate migrated/seeded QA database context, integrated load is BLOCKED deliberately. To repeat the isolated load as well, set `SAFEPATH_BENCHMARK_QA_CONTEXT` to a private JSON context before that same command, or use `--qa-context`. See [README.md](README.md) for macOS/Windows setup, strict loopback database/Redis15/OSRM requirements and flags. An unsuccessful load makes the command exit 1 while retaining reports. `--quick --offline --publish` is the shorter offline tool check, not a replacement for full acceptance.

For labelled datasets add `--flood-dataset` / `--vehicle-dataset`; `--compare-baseline` compares single-frame vs production tiling on identical vehicle GT. Do not publish examples unless rights and manifest permission allow it. Review free-form provenance manually; automatic redaction is pattern-based.

With Docker, rebuild the frontend after publishing a new static bundle. The final Node 22 Docker build passed and all five original containers are healthy. This local app has been rebuilt; `/benchmark` requires no public Run Benchmark action and does not execute models from the browser.

## Before presenting

You can state that the two exact ONNX models ran on real stored frames, publish the scoped timing numbers above, and demonstrate 52 specification scenarios plus downloadable reproducible artifacts. Use [JUDGE_PRESENTATION.md](JUDGE_PRESENTATION.md) for the three-minute script.

Before claiming accuracy, prepare a legally usable independent human-labelled, camera/scene-separated test dataset and run both evaluators. Before claiming capacity, resolve the 10-VU routing timeouts and repeat bounded load tests. Verify capture timestamps and camera publication rights before presenting source images. Do not claim field safety, rain/night accuracy, Google-equivalent ETA or full camera uptime from this run.

Independent final review found no remaining HIGH/CRITICAL issues in the bounded benchmark code review; the accuracy, load and camera limitations remain open. Agents used: benchmark_evaluation (audit/evaluators/scenarios), benchmark_dashboard (UI), benchmark_review (independent review), with orchestration, inference/load execution and integration performed by the main agent. Flash was unavailable; agents inherited the active model.

## Exact changed/created files

- `README.md`
- `backend/tests/test_benchmark_evaluation.py`
- `backend/tests/test_benchmark_route_scenarios.py`
- `backend/tests/test_benchmark_runner.py`
- `docs/CORE_CAMERA_AND_PERFORMANCE_ACCEPTANCE.md`
- `docs/FLOOD_MODEL_TRAINING.md`
- `docs/benchmark/BENCHMARK_AUDIT.md`
- `docs/benchmark/DATASET_ANNOTATION.md`
- `docs/benchmark/IMPLEMENTATION_REPORT.md`
- `docs/benchmark/JUDGE_PRESENTATION.md`
- `docs/benchmark/README.md`
- `frontend/e2e/benchmark-dashboard.spec.ts`
- `frontend/e2e/benchmark-live.spec.ts`
- `frontend/public/benchmark/benchmark_report.md`
- `frontend/public/benchmark/benchmark_results.csv`
- `frontend/public/benchmark/camera_metrics.json`
- `frontend/public/benchmark/commands.json`
- `frontend/public/benchmark/environment.json`
- `frontend/public/benchmark/flood_metrics.json`
- `frontend/public/benchmark/inference_latency.png`
- `frontend/public/benchmark/inference_metrics.json`
- `frontend/public/benchmark/limitations.md`
- `frontend/public/benchmark/load_test_metrics.json`
- `frontend/public/benchmark/methodology.md`
- `frontend/public/benchmark/routing_metrics.json`
- `frontend/public/benchmark/summary.json`
- `frontend/public/benchmark/vehicle_metrics.json`
- `frontend/src/app/benchmark/page.tsx`
- `frontend/src/components/benchmark/BenchmarkDashboard.tsx`
- `load_tests/k6_route_search.js`
- `reports/hackathon-benchmark/benchmark_report.md`
- `reports/hackathon-benchmark/benchmark_results.csv`
- `reports/hackathon-benchmark/camera_metrics.json`
- `reports/hackathon-benchmark/commands.json`
- `reports/hackathon-benchmark/environment.json`
- `reports/hackathon-benchmark/flood_metrics.json`
- `reports/hackathon-benchmark/inference_latency.png`
- `reports/hackathon-benchmark/inference_metrics.json`
- `reports/hackathon-benchmark/limitations.md`
- `reports/hackathon-benchmark/load_test_concurrent_regression_attempt.json`
- `reports/hackathon-benchmark/load_test_first_attempt.json`
- `reports/hackathon-benchmark/load_test_metrics.json`
- `reports/hackathon-benchmark/methodology.md`
- `reports/hackathon-benchmark/routing_metrics.json`
- `reports/hackathon-benchmark/summary.json`
- `reports/hackathon-benchmark/vehicle_metrics.json`
- `scripts/benchmark_eval/__init__.py`
- `scripts/benchmark_eval/datasets.py`
- `scripts/benchmark_eval/evaluation.py`
- `scripts/benchmark_eval/local_server.py`
- `scripts/benchmark_eval/metrics.py`
- `scripts/benchmark_eval/operational.py`
- `scripts/benchmark_eval/performance.py`
- `scripts/ml/evaluate_flood_model.py`
- `scripts/ml/export_flood_onnx.py`
- `scripts/run_hackathon_benchmark.py`

Generated private logs, browser screenshots and bytecode are ignored or stored outside the repository. The camera URL manifest generated by tests was restored to its original committed bytes.
