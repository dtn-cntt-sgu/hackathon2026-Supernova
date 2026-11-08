# Explicit camera inspection and local sign-in repair

Date: 8 November 2026, Asia/Ho_Chi_Minh. This request supersedes the earlier ban on viewing inference: the user explicitly authorized analysis when selecting Overlay or choosing a camera in the landing page's flood-risk inspection section.

- Opening a camera and refreshing source imagery remain fetch-only. Selecting **Phát hiện AI (Overlay)** makes an explicit POST to `/api/v1/cameras/{id}/analysis`. Selecting a location in landing section02 also analyzes that selected camera. Merely loading the homepage/gallery does not start city-wide inference.
- Original bytes and overlay share an immutable snapshot ID/content hash/model version. If the source changes after display, the client retries once against the returned current source identity. No legacy `_analyzed.jpg` fallback is used. An analyzed-image request without a snapshot ID is rejected. This prevents old test/other-frame overlays from being displayed against a new source picture.
- The bounded lazy model executor is shared with route inference, with a distinct view cache. A viewing result remains non-routing/UNKNOWN; camera selection does not verify capture time, segment correspondence or road safety.
- Removed enhancement UI/API/helper, enhancement function/config, enhanced preprocessing/detector branch, derived-image generation and obsolete enhancement benchmark/tests. Replaced quality tests retain validation of the original image. Historical nullable database columns/frozen migrations and legacy placeholder/derivative exclusion fingerprints remain for compatibility and safe rejection; no destructive data/schema deletion is performed.
- Camera source is displayed once outside the image as Vietmap CDN. One display field uses retrieval time: **Thời gian ảnh (nhận lúc)**. The raw retrieval timestamp is not fabricated into a verified capture timestamp. Stale labels are omitted from camera UI while backend freshness/permission checks remain enforced.
- Removed the technical Zero-Mock coordinate badge from news.

## Authentication root cause

The running frontend had AUTH_SECRET, while the older running backend container had no AUTH_SECRET at all. Signed account synchronization therefore returned401. The root environment and running frontend secret were compared privately and matched; no secret values were logged. Recreating the local frontend/backend with the existing shared Compose AUTH_SECRET binding repairs the mismatch. Signed identity verification, ownership checks and rejection of anonymous identity sync remain enabled. Added frontend logging reports only the backend rejection status, without exposing account/token data.

No credentials were replaced with a fixed fallback and no authentication checks were bypassed. Real Google authorization is interactive; a successful redirect/configuration and server signature checks do not substitute for a completed user login.

## Validation

- Full backend regression on retained disposable QA database and Redis15: **431 PASS,15 SKIP**,108.99s. Three additional new endpoint tests: **3 PASS**. The endpoint tests were added after the complete run started and are reported separately.
- Earlier selected interaction/auth/permission tests:59PASS. Original-only/model regressions:44PASS,1SKIP (torch absent). These overlap the complete suite and are not added together.
- Frontend type-check PASS; unit tests10PASS, including actual-provider source labeling.
- Real Vietmap-source original-only inference returned READY in approximately4.1s for the selected frame, with exact original/overlay identity. The tested frame had0 detected vehicles; this is an observed model output, not a fabricated positive count or an accuracy claim. Water-pixel ratio is not proof of street flooding or water depth.
- Backend/frontend Docker builds PASS. Final Chromium browser acceptance on localhost3000: **13 PASS,0 FAIL**,41.8s. Cases cover explicit Overlay with real source/model, landing-selection analysis, source labels, removed enhancement/news badge, mobile/tablet, hydrology, guest access rejection and real routes. The first browser attempt started before frontend restart completed and failed connection checks; its log is retained separately. The readiness smoke assertion now accepts the explicit development schema state as well as migrated staging/production state, without accepting unavailable readiness.
- Independent reviewer:37targeted testsPASS, no Critical/High findings. Two MEDIUM issues were corrected: reused same-hash source files retain truthful new retrievalmtime, and provider labels/fetched headers reflect real metadata. Regression tests for the retrieval fix plus endpoint checks:8PASS.
- Runtime auth: shared frontend/backend HMAC signature PASS; OAuth configuration present; CSRF/sign-in flow returns a redirect to accounts.google.com. No real Google account consent/session was completed by the agent.
- Five local Docker services healthy; current frontend/backend images are running on localhost3000/8000. No production services were deployed.

No commit or push was requested/performed. The update targets the existing local development app, not a production deployment.

Logs: `/tmp/safepath-camera-full-regression.log`, `/tmp/safepath-camera-review-fixes.log`, `/tmp/safepath-camera-browser-final.log`, `/tmp/safepath-camera-units-accepted.log`, `/tmp/safepath-camera-auth-runtime.json`, `/tmp/safepath-camera-build-final.log`, `/tmp/safepath-camera-security-final.log`. Security/redaction scanner and Git diff checks PASS. Browser source-image SHA and overlay input SHA are checked separately against the analysis response, preventing a caption-only or mismatched overlay acceptance.

Modified areas: camera analysis/vision/main contracts/config, shared camera viewer/snapshot UI, landing/news, local/production Compose flags, original-only quality tests and interaction E2E. Removed `scripts/benchmark_enhancement.py` and obsolete enhancement test modules, replacing them with original-image quality tests. The nullable historical DB field is retained only to preserve migrations/data, and known legacy derivative/placeholder exclusions remain security checks.
