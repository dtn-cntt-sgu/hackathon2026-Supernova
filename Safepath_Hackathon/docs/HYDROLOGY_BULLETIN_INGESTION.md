# Official Phú An / Nhà Bè daily hydrology bulletins

## Sources and verified semantics

- Discovery: https://www.phongchonglutbaotphcm.gov.vn/index.php/da-ba-o-tha-y-v-n
- Verified PDF: https://www.phongchonglutbaotphcm.gov.vn/phocadownload/2026/11-2026/HCMC_TVHN_20261107.pdf
- Supplemental national bulletin: https://www.nchmf.gov.vn/kttv/vi-VN/1/ban-tin-du-bao-thuy-trieu-10-ngay-toi-tu-ngay-29-10-den-ngay-07-11-2026-post54291.html

The verified PDF is bulletin 311/2026, issued 09:06 on 7 November 2026 in Asia/Ho_Chi_Minh. It contains eight observed extrema for **6 November**, plus 40 forecast extrema for 7–11 November, across Phú An and Nhà Bè. Both daily highs and both daily lows are retained, including their individual times. Neither yesterday's maximum nor today's forecast is a current water-level measurement.

Source units are metres. The PDF does not identify a vertical datum specifically for these two stations; the API records `UNSPECIFIED_IN_BULLETIN`. A datum annotation for Vũng Tàu must not be copied onto these stations. The national page's body describes 7–16 November despite its older URL slug; it provides supplemental coastal information, not replacement observations for these two stations.

No documented public observation API was found in the supplied sources. The implementation reads the publicly accessible official PDF. This finding does not imply a blanket redistribution licence. Production never reads the test fixture.

## Collection and storage

`hydrology_bulletin.py` discovers links from the official listing and its newest monthly page, then selects the newest `HCMC_TVHN_YYYYMMDD.pdf`. The verified filename above is not a production fallback or a pinned feed. Only allowlisted HTTPS portal paths are fetched; redirects, external hosts and traversal are rejected.

The worker runs at startup and polls at most once per 30 minutes by default. Redis and local locks coordinate collection. Failures back off from 30 minutes to six hours. Requests have a ten-second timeout, a total operation deadline, HTML/PDF byte limits and a bounded PDF extraction task. Successful documents are deduplicated by SHA-256; failed fetching/parsing/persistence keeps the last valid bulletin.

Two additive tables, `hydrology_bulletins` and `hydrology_bulletin_events`, preserve the source URL, bulletin date, issuance/retrieval times, source unit/datum and normalized events. Events contain station ID/name, `OBSERVED`/`FORECAST`, `HIGH_TIDE`/`LOW_TIDE`, slot, source date, water level, event time, original value/time tokens and missing reason. `ct`, `-` and `*` remain missing, never zero. Times are normalized to Asia/Ho_Chi_Minh, including midnight rollover.

The parser supports the verified two-station, five-day table layout. A changed/ambiguous layout is rejected rather than guessed. A scanned PDF without usable text requires a separately validated parser; there is no silent OCR or invented data fallback.

## API and UI

- `GET /api/v1/hydrology/bulletin`: latest stored bulletin with all normalized events and source metadata.
- `GET /api/v1/hydrology/latest`: existing observations response, with an additional `bulletin` field.
- `GET /api/v1/weather-tide`: retains instantaneous-observation semantics. Daily extrema are not substituted into `tide_level_meters`.

Bulletin status is `DAILY_BULLETIN`, `STALE` after the configured age (36 hours by default), failed polling or disabled collection, or `UNAVAILABLE` when no valid bulletin exists. Observed extrema are `OBSERVED_HISTORICAL`; forecasts are `FORECAST_VALID` or `FORECAST_PAST`; missing value/time is `UNAVAILABLE`.

The environmental panel shows the issue time, forecast day, separate historical observations and forecasts, both stations' highs/lows, original units, unknown datum and source PDF link. It explicitly says these are daily extrema rather than the current level. Instantaneous tide remains unavailable until a verified instantaneous feed is configured.

Daily bulletins do not write to the existing live-observation table, instantaneous tide cache or Risk Engine. A high-tide forecast alone cannot establish street flooding or route risk. Camera proxy and Route AI admission rules are preserved.

Configuration: `HYDROLOGY_BULLETIN_ENABLED`, `HYDROLOGY_BULLETIN_POLL_SECONDS`, `HYDROLOGY_BULLETIN_TIMEOUT_SECONDS`, `HYDROLOGY_BULLETIN_MAX_BYTES`, `HYDROLOGY_BULLETIN_MAX_AGE_HOURS`.

## Files changed for this integration

- Backend: `backend/app/services/hydrology_bulletin.py`, `backend/app/services/hydrology_service.py`, `backend/app/db/models.py`, `backend/app/core/config.py`, `backend/app/main.py`.
- Dependency/config: `requirements.txt`, `.env.example`, `docker-compose.yml`.
- Frontend: `frontend/src/components/HydrologyBulletinPanel.tsx`, `frontend/src/components/SpatialDashboard.tsx`, `frontend/src/hooks/useLiveObservations.ts`, `frontend/src/services/api.ts`, `frontend/src/types/contracts.ts`.
- Tests: `backend/tests/test_hydrology_bulletin.py`, `backend/tests/fixtures/hydrology/HCMC_TVHN_20261107.pdf`, the accompanying `.txt` and `.provenance.json`, `frontend/e2e/hydrology-bulletin.spec.ts`.
- Documentation: this file and `docs/UI_WEATHER_OVERLAY_FIXES.md`.

Other outstanding mobile, weather and selected-camera overlay changes are described in `UI_WEATHER_OVERLAY_FIXES.md`; no pre-existing untracked user files were committed or removed.

## Validation

The real PDF fixture is 318,977 bytes, SHA-256 `f9ca5b67a2f35e0e52b6ca4d02bf32d890f83c609f85164acbdb7e6141678e60`; its provenance manifest records the original source. Unit/integration coverage includes the actual PDF, all 48 events, missing tokens, date/time rollover, source selection, URL/size limits, deduplication, transaction rollback, backoff and last-good-data retention. The independent reviewer reported no high or medium findings and independently passed all 41 bulletin tests.

The actual collector fetched and persisted the official PDF into local PostgreSQL; both hydrology endpoints returned `DAILY_BULLETIN` and all 48 events. The weather endpoint returned real Open-Meteo rainfall `0.0` with its source timestamp, while instantaneous tide remained null. Local Docker frontend/backend production builds and security/redaction checks passed. Live browser tests use the running services without mocking the hydrology API or camera model.

Agents used: frontend/mobile workers for responsive layout, backend workers for bulletin ingestion, source auditors for PDF semantics, and independent reviewers for final code and source-data checks. The main agent integrated configuration, endpoints and the bulletin UI, inspected the diffs and validated the running app. No high or medium findings remain.

Final results:

- Backend regression: **401 PASS, 0 FAIL, 15 SKIP**, 90.49 seconds. Skips: 14 explicitly gated live OSRM/GIS tests, one PyTorch test because `torch` is absent. The first run had one OSRM availability failure while OSRM was deliberately stopped for the Docker build; after restart its ten-test group passed, followed by the full clean run above.
- Live Chromium acceptance: **8 PASS, 0 FAIL**, 29.9 seconds. Includes official daily bulletin on mobile, responsive route controls at 375/390/768/900px, camera metadata, tablet navigation and real snapshot-bound AI overlay.
- Bulletin unit/integration tests: **41 PASS** (also included in the full regression).
- Frontend/backend production Docker builds: **PASS**. Security/redaction audit and `git diff --check`: **PASS**.
- Commands: `.venv/bin/python -m pytest -rs`; from `frontend`, `PLAYWRIGHT_BASE_URL=http://localhost:3000 PLAYWRIGHT_EXTERNAL_SERVER=1 ./node_modules/.bin/playwright test e2e/hydrology-bulletin.spec.ts e2e/map-responsive.spec.ts e2e/camera-live-overlay.spec.ts`.
- Logs: `/tmp/safepath-hydrology-full-regression-final.log`, `/tmp/safepath-hydrology-final-browser.log`, `/tmp/safepath-bulletin-deploy.log`. Mobile bulletin screenshot inspected: `/tmp/safepath-hydrology-mobile.png`.

No commit or push was performed for this work.
