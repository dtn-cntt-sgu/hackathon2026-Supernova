# SafePath measured benchmark

Run: 2026-11-08T02:46:39.527603+00:00 · Commit: `d80b15c6e25b753ac0ea1e34222d99ed42d47131` · Dirty: True

## flood

**NOT EVALUATED** — No labelled test manifest supplied; no accuracy can be measured

## vehicle

**NOT EVALUATED** — No labelled test manifest supplied; no accuracy can be measured

## inference

**LIMITED** — Real-frame latency only; NOT AN ACCURACY BENCHMARK. Single host, serial calls, camera sample not representative.

## routing

**LIMITED** — Specification/unit scenarios, with labelled synthetic evidence; NOT field AI accuracy or road-safety guarantee.

## camera

**LIMITED** — Point-in-time local metadata plus at most3 source-image probes; registry != active cameras. No fleet sweep, no uptime claim.

## load

**FAILED** — One iteration per VU on isolated local route server, no external providers/workers. Short bursts, not sustained production capacity.

## Commands and exit codes

```json
[
  {
    "section": "flood",
    "exit_code": 0,
    "elapsed_seconds": 0.0004270000208634883
  },
  {
    "section": "vehicle",
    "exit_code": 0,
    "elapsed_seconds": 0.0545123330084607
  },
  {
    "section": "inference",
    "exit_code": 0,
    "elapsed_seconds": 480.82961729101953
  },
  {
    "section": "routing",
    "exit_code": 0,
    "elapsed_seconds": 5.752937709010439
  },
  {
    "section": "camera",
    "exit_code": 0,
    "elapsed_seconds": 0.37011879100464284
  },
  {
    "section": "load",
    "exit_code": 1,
    "elapsed_seconds": 13.257947750011226
  },
  {
    "command": "rerun isolated k6 after socket guard fix and regression completion",
    "exit_code": 1,
    "scope": "Final measured local load; earlier failures retained separately"
  },
  {
    "command": "rerun route_scenarios with supplemental specification cases; format CSV and sanitize public artifacts",
    "exit_code": 0
  }
]
```

See JSON/CSV for measured values, methodology.md and limitations.md.

## Measured results in this run

| Model | Model-only p95 range,3runs | Pipeline-file p95 range,3runs | Samples |
|---|---|---|---|
| vehicle_detector | 593.78–620.33ms | 2598.18–3626.34ms |300 model-only,60 pipeline-file |
| flood_segmenter | 11.19–11.50ms | 16.68–18.95ms |300 model-only,60 pipeline-file |

CPUExecutionProvider node execution was observed for both models. ORT tracing was enabled; input images are private local camera snapshots, not a representative labelled accuracy dataset.

Routing: 52/52 specification cases pass. This is not field AI accuracy. Camera: 796 registered; 3/3 sampled local originals valid; zero verified capture timestamps in the sample. Stored overlay metadata consistency is a separate readonly count, not byte-level correctness or uptime.

## Load test — FAILED

Initial cold run timed out at5s. A repeated load run with enforced loopback-only sockets and no parallel regression still failed at10VU;25/50VU were not attempted after fail-stop. Retain failures and do not claim production capacity.

| VUs | Requests | Mean(ms) | p95(ms) | Error rate | Timeout rate |
|---|---|---|---|---|---|
| 1 |1|1685.688|1685.688|0|0|
| 10 |10|5000.284299999999|5000.61145|1|1|

## Accepted regression and known blockers

558 backend tests PASS/15SKIP (14 opt-in live cases,1 legacy PyTorch dependency missing). Static frontend lint/typecheck and12unit tests PASS. Earlier regression overlapped load and encountered DB connection timeouts; the final accepted run was sequential. No weights/config/production deployment changed. Flood/vehicle field accuracy remain NOT EVALUATED; dataset absent. Checkpoint parity BLOCKED without PyTorch/paired evaluation.

See commands.json, docs/benchmark/README.md and JUDGE_PRESENTATION.md. Raw logs are private local files, not publicly served.
