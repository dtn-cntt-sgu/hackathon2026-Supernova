# Mobile layout, weather freshness and selected-camera overlays

Historical acceptance report. The later production-readiness request supersedes viewing inference: map/Monitor camera viewing now uses the original-image proxy only; the legacy analysis endpoint returns410. See `PRODUCTION_READINESS_REPORT.md`.

## Behavior

- Mobile map controls reserve separate header, camera-control, voice-HUD and bottom-sheet areas. Peek/preview sheets hide the form instead of clipping it under the handle. The traffic legend clears the sheet and disappears while the form is expanded. Narrow weather cards stack vertically. A compact menu preserves navigation on mobile/tablet.
- Route search no longer automatically opens the first camera inspector over the route controls. Camera selection remains explicit.
- Camera gallery metadata sits below the picture. Internal source-status codes such as `RECENTLY_RETRIEVED_CAPTURE_UNKNOWN` are not rendered. Capture-time uncertainty remains visible in Vietnamese.
- Weather grid and aggregate caches validate the original provider observation time and limit their TTL to the remaining 15-minute freshness window. Invalid/stale cache entries cause a real fetch; timestamps are never refreshed to disguise old measurements. Valid zero rainfall is retained.
- Hydrology missing readings and alarm states are nullable, with an explicit reason. A homepage URL is insufficient provenance for a station observation. Unverified historical/test rows are excluded from current measurements without deleting station history. Free-text ingestion cannot publish an unverified bulletin as a live observation; dates/timezones and a specific verified source are required. Existing hydrology tests now use rollback transactions and an isolated cache.

## AI behavior clarified by the user

The user requested that an overlay be prepared automatically when camera data is available. Opening a **selected map camera** now calls `POST /api/v1/cameras/{id}/analysis`. The endpoint checks camera registry membership, viewing permission, rate limits and source validation, then stores immutable original bytes and requests bounded inference. The Monitor gallery and plain proxy requests do not trigger AI, and no city-wide inference job is created.

Viewing and route inference share the lazy model pipeline and bounded executor. Viewing results have a separate `camera:view_ai` cache namespace. They always remain `NOT_VERIFIED_FOR_ROUTING` with unknown route risk, even when model detections are available. Output IDs include source SHA-256 and the model-manifest fingerprint. Original/enhanced/overlay URLs point to that same immutable snapshot. Viewing auxiliary outputs are kept away from the legacy route-image directory.

`CAMERA_VIEW_AI_ENABLED=true` and `CAMERA_VIEW_AI_TIMEOUT_SECONDS=20` control this feature. Existing route-only admission, source permissions, camera limits and model configuration remain in force. Native inference retains its resource slot after an HTTP timeout. There is no automatic AI in the Monitor gallery.

The inspector only displays metrics belonging to the current viewing response; it cannot reuse legacy confidence, quality, density or routing-eligibility labels from another frame. Its source link follows the configured viewing provider. Explicit immutable-image requests no longer fall back to an unrelated legacy frame.

## Verification

After the official daily bulletin integration, the final complete run passed **401 backend tests (15 skipped)** and **8 live browser tests**. The earlier figures below document the initial mobile/overlay acceptance. Final details are in `HYDROLOGY_BULLETIN_INGESTION.md`.

- Complete backend suite: **359 passed, 15 skipped** before the final auxiliary-output guard; subsequent targeted tests cover that guard and route/view separation.
- Live browser suite: **7 passed in 28.7 seconds** against Docker `localhost:3000`: map layouts at 375/390/768/900px, compact tablet navigation, metadata placement/raw-status removal, and a real decoded AI overlay bound to the source snapshot. No API interception or fabricated camera images.
- Frontend production build and security/redaction checks passed.
- Real selected-camera inference returned `READY`, detected **6 vehicles** in the tested frame, served a JPEG overlay and matched its inference-input SHA-256 to the original frame. This is an observed test result, not a claim of detection accuracy or a permanent vehicle count.
- Real weather endpoint returned HTTP 200 with Open-Meteo rainfall `0.0`, `LIVE`, and its original observation timestamp. Instantaneous hydrology returns an explicit unavailable/unverified state with no fabricated station measurement. Official daily bulletin data is now integrated separately as described below.

Screenshots were inspected locally at `/tmp/safepath-fixed-375.png` and `/tmp/safepath-fixed-overlay.png`.

## Official daily hydrology integration

The supplied official portal now provides daily Phú An/Nhà Bè bulletins through automatic PDF discovery and ingestion. See [HYDROLOGY_BULLETIN_INGESTION.md](HYDROLOGY_BULLETIN_INGESTION.md) for exact files, endpoints, source provenance and semantics. Historical observed extrema and forecasts are displayed separately. An instantaneous gauge feed remains unconfigured (`VERIFIED_FEED_NOT_CONFIGURED`); daily extrema are never substituted into the live water-level field. No artificial tide, zero-level fallback, forecast-as-observation, or test-fixture measurement was substituted.

Skipped tests: 14 explicitly gated live OSRM/GIS tests in the default suite, and one PyTorch equivalence test because `torch` is absent. The browser route checks above used the running real OSRM/API. Changes in this fix remain local unless separately committed/pushed.
