# SafePath Hackathon — Core Stability & Logic Audit / Remediation Plan

**Repository:** https://github.com/giakhoi0123/Safepath_Hackathon  
**Baseline:** `main` SHA `9495e84e327265eccb0be67120734630741d8daf` (2026-11-07 15:38 ICT). Lỗi logic core được đối chiếu trực tiếp trên mã ứng dụng không đổi sau PR #16; workflow CI/CD được cập nhật tại PR #16.  
**Mục đích:** hoàn thiện tính đúng đắn, ổn định và hiệu suất hệ thống **trước** khi bàn tiêu chí chấm điểm.  
**Độ tin cậy:** kiểm tra mã nguồn, manifest, workflow và log GitHub Actions; **chưa** chạy Docker, GPU, TomTom live hay test browser trên máy của nhóm. `Có file` ≠ `PASS runtime`.

## Trạng thái nền

- Đã có `backend/app/main.py`, 30 service backend, `frontend/src` và MapLibre, 29 file test backend, 28 file E2E frontend, các script tạo OSRM/nhập OSM, ba workflow GitHub Actions (`ci.yml`, `docker-image.yml`, `cd.yml`), model Flood U-Net và VGG16-SSD.
- Run Docker image ở commit **cũ** `764ae37e` đã FAILED tại bước push vì GHCR `denied: permission_denied: write_package`. PR #16 đã chuyển tên package sang `ghcr.io/${{ github.repository }}/backend|frontend` và cập nhật workflow; **chưa xác minh** kết quả run mới (đang in_progress khi kiểm tra), không thể khẳng định đã hết lỗi.
- PR #16 đã mở rộng `ci.yml` để chạy `pytest backend/tests/ -v` với PostGIS/Redis services và bước Docker build validation. Tuy nhiên chưa thấy Playwright E2E trong workflow; có nguy cơ test live cần OSRM/network fails vì CI không khởi động OSRM. `cd.yml` mới chỉ **build/push images** và xuất summary, chưa triển khai Cloud Run/AWS. Chưa có biên bản E2E chứng minh toàn hệ thống đang chạy.

## Quy ước mức độ

- **BLOCKER**: có thể khiến hệ thống không khởi động, sai quyền truy cập, không có cảnh báo, không tìm được tuyến hoặc ngụy tạo an toàn.
- **P0**: sai logic lựa chọn đường / nguồn dữ liệu / ước lượng thời gian; phải sửa trước demo.
- **P1**: hiệu năng, độ bền, giám sát, chi phí và hành vi realtime.
- **P2**: trải nghiệm, tài liệu, tối ưu nâng cao.
- **Xác nhận** = câu lệnh/đoạn mã đã đối chiếu. **Cần thử** = rủi ro hợp lý nhưng chưa có log chạy thực.

## A. BLOCKER — lỗi xác nhận từ mã nguồn

| ID | File / nơi phát sinh | Lỗi | Cách sửa cụ thể | Điều kiện nghiệm thu |
|---|---|---|---|---|
| B01 | `backend/app/main.py` `background_vision_worker_loop`; `backend/app/schemas/contracts.py` `WebSocketAlertMessage` | Worker gọi `WebSocketAlertMessage(alert_id, hazard_type, suggested_reroute, timestamp, ...)` trong khi schema yêu cầu `event_id, type, severity, source, observed_at, message`. ValidationError có thể bị bắt ở tầng ngoài, làm mất cảnh báo. | Tạo một factory typed `build_camera_alert(...)` sử dụng schema chuẩn, định nghĩa loại `CRITICAL_FLOOD_ALERT`, mapping source/cam_id/expiry, test end-to-end WebSocket. Phân biệt cảnh báo quan sát với xác nhận ngập. | Unit validate message thành công; WebSocket browser nhận payload đầy đủ và popup xuất hiện, có dedupe/expiry. |
| B02 | `backend/app/main.py` `/api/v1/user/sync`, `/api/v1/user/profile`, preferences, places, history; `frontend/src/app/api/v1/[...path]/route.ts` | API nhận `provider_account_id`, `email` hoặc `X-User-Id` client tự cung cấp mà không kiểm tra chứng thực server-side; có nguy cơ giả danh/đọc hoặc sửa dữ liệu người khác. Proxy còn chuyển tiếp `x-user-id` từ request trình duyệt. | Yêu cầu token/session đã xác minh (Google ID token ở server hoặc signed internal session/JWT), derive user_id từ verified claims; không lấy định danh làm chứng thực; bảo vệ toàn bộ endpoints riêng tư và hạn chế sync user. | Request giả header/Google sub trả 401/403; token của A không đọc hoặc sửa hồ sơ B; test authorization tự động. |
| B03 | `backend/app/services/risk_engine.py` (khoảng dòng 123–129) | Chỉ tính flood nếu **cùng camera có cả** `flood_ratio` và `traffic_density_score`. Model nước có kết quả nhưng vehicle model lỗi thì mất bằng chứng ngập. | Chia flood evidence và traffic occupancy thành hai channel độc lập; kiểm soát `None`, `NaN`, tỷ lệ 0–1, freshness và quyền dùng. Flood score không nhận trọng số occupancy một cách ngầm định. | Test `flood present + traffic absent` vẫn cảnh báo; `traffic present + flood absent` không suy ra ngập. |
| B04 | `backend/app/services/risk_engine.py` (~255–275) | Chuỗi `if/elif` ưu tiên điểm camera trước: điểm camera thấp có thể che cảnh báo đóng đường/ngập từ tin đủ điều kiện. | Tạo tập hazard candidates độc lập (flood image/news/closure/incident), lọc theo eligibility và lấy hazard đủ điều kiện nghiêm trọng nhất; ghi nguồn quyết định. | Tin ROAD_CLOSURE đủ điều kiện + camera 0.01 → CRITICAL; camera mất kết nối + tin hợp lệ → CRITICAL. |
| B05 | `backend/app/services/routing.py` (~810–840) | Giải thích có câu “Không phát hiện nguy cơ ngập úng” khi chỉ biết congestion, hoặc “Tất cả các đoạn đã xác thực an toàn” không đủ chứng minh toàn tuyến. | Chuẩn hóa giải thích theo provenance: UNKNOWN khác SAFE, ghi rõ độ phủ nguồn/số đoạn thiếu; tách traffic_status khỏi flood_risk. | Không câu khẳng định toàn tuyến an toàn khi có đoạn UNKNOWN; text E2E đúng với JSON. |
| B06 | `backend/app/services/traffic_providers/tomtom.py` | `roadClosure=true` hiện đưa chung vào `TrafficStatus.CONGESTED`, rồi giới hạn vận tốc tối thiểu 0.5m/s để tính delay → chưa loại cạnh đóng khỏi quyết định routing. | Thêm trạng thái `CLOSED`/separate `road_closure`; xác minh matched direction; chặn hoặc phạt vô hạn cạnh đã xác minh đóng, kích hoạt reroute; tránh suy luận closure nếu flow không match. | Test 1 tuyến qua CLOSED + 1 tuyến vòng → đề xuất tuyến vòng; trường hợp tất cả đóng → cảnh báo NO_SAFE_ROUTE (không giả an toàn). |
| B07 | `backend/app/services/routing.py` | Xếp hạng **chỉ các alternative do OSRM trả về**. Nếu tất cả đi qua đoạn nguy hiểm, không có cơ chế cắt cạnh và tìm graph path mới. | Thiết kế v1: candidate route + hazard filter + `no safe alternative` trung thực. V2: exclude edge/segment ở routing engine hỗ trợ edge exclusion, rebuild/cost routing, hoặc engine graph có custom weights. Không tự chế tuyến polyline. | Scenario có cạnh đóng buộc chọn đúng đường tránh hợp lệ; mọi option rủi ro => không tuyên bố đã tránh được. |
| B08 | `frontend/src/services/api.ts`, `docker-compose.yml` | WebSocket mặc định `ws://localhost:8000`; URL này sai khi dùng domain public/HTTPS và có thể bị chặn mixed content. Next.js REST proxy không proxy được WebSocket. | Tách WS gateway với URL `wss://` ở deploy, reverse-proxy hỗ trợ upgrade, env theo environment; hoặc SSE nếu phù hợp. Gửi/nhận JSON schema thống nhất. | HTTPS web app kết nối wss thành công trên laptop/mobile không cần localhost. |
| B09 | `.github/workflows/docker-image.yml`, GHCR permissions | Run **trước PR #16** bị `permission_denied: write_package` cho cả FE/BE. PR #16 đã đổi package path và workflow nhưng **chưa có kết quả run mới**. | Kiểm tra quyền repo Actions/GITHUB_TOKEN `packages:write`, package ownership/connected repo, existing package access, image naming; đăng ký package mới thuộc repo nếu cần. Không đẩy key qua workflow. | Workflow `main` xanh trên SHA **mới**, image pull bằng đúng quyền, tag SHA bất biến. |

## B. P0 — đúng dữ liệu, mô hình, ETA và lựa chọn tuyến

| ID | Nơi | Vấn đề | Sửa / cập nhật | Kiểm thử chấp nhận |
|---|---|---|---|---|
| C01 | `risk_engine.py`; `traffic_news.py` | News khớp tên đường chỉ bằng substring trong title/summary; chưa chứng minh đúng cạnh/chiều/cầu vượt. | Geocode sự kiện thành geometry/time interval, spatial join có hướng/đoạn, manual verification status; ambiguous => CONTEXT_ONLY. | Tin cùng tên đường nhưng khác quận không đổi risk tuyến. |
| C02 | `routing.py` `_get_flood_prone_way_ids()` | Hàm dữ liệu ngập lịch sử tồn tại nhưng không thấy được gọi trong `find_safe_route()`. | Nối historical_flood_points ↔ edges theo spatial validated; historical là **prior/context**, không phải bằng chứng đang ngập; dùng kết hợp mưa/triều với weight được hiệu chỉnh. | Có/không có lịch sử cập nhật context đúng, nhưng không tự thành CRITICAL hiện tại. |
| C03 | `routing.py` step→OSM edge | Chọn nearest edge candidate, không xác nhận edge/chiều lái OSRM thực sự. | Direction-aware map matching với tolerance topological/geometric, bridge/tunnel, confidence; không gắn hazard nếu unverified. | Test đường song song/cầu vượt/2 chiều khác nhau tránh false match. |
| C04 | `routing.py` ETA | `OSRM duration + sum(traffic_delay)`; `ranking_cost=OSRM duration+1.5×delay+flood penalty`; API khác route provider có thể dùng free-flow không cùng cơ sở với OSRM. | Xác minh baseline semantics. Ưu tiên một provider cho geometry+ETA hoặc đoạn khớp chính xác mới bổ sung delay; tránh cộng đúp; đo `traffic_coverage_ratio` và không coi ETA bán phần là full-traffic ETA. | Cùng A→B có source, coverage, ETA minh bạch, test không double-count, sensitivity khi delay tăng. |
| C05 | `tomtom.py` | Mỗi step >=40m gọi Flow theo midpoint, cache grid làm tròn .0001 độ; match trong 60m + bearing 85°, có nguy cơ sai đường giao/cầu vượt. | Cache key kèm provider/version/direction/road ID; bounded sample, snap direction/lane, min-coverage/confidence; check coordinate order, invalid speed, closure. | Fixture đối diện đường và cầu vượt không dùng chéo flow; API errors → UNKNOWN. |
| C06 | `tomtom.py` | GET Flow per cell có concurrency max 5 **mỗi request**; tạo `AsyncClient` mới mỗi route. Khi nhiều user dễ vượt quota/tăng latency. | Shared httpx client/pool, token bucket global (Redis), retry giới hạn, 429 backoff, circuit-breaker phù hợp, caching/stale policy; giới hạn fan-out. | Load test 30 concurrent, quota không vượt, latency p95/requests per route lưu log. |
| C07 | `schemas/contracts.py` `RouteSearchRequest` | Chỉ có origin/destination. Chọn `motorcycle/car` trong hồ sơ chưa ảnh hưởng OSRM profile `/route/v1/driving`. | Bổ sung mode validated + routing strategy/capability rõ. V1 chỉ cam kết car-driving graph; không tự giả đường riêng xe máy; v2 dùng profile hợp lệ được kiểm thử. | Chọn vehicle thực sự đổi graph/constraint, hoặc UI ghi giới hạn rõ ràng. |
| C08 | `risk_engine.py` / model flags | `CAMERA_ROUTING_EVIDENCE_PERMITTED=False` đúng là gate an toàn nhưng khiến dữ liệu ảnh không ảnh hưởng ranking nếu chưa verified view. | Tạo workflow validate camera source/license, GPS, bearing, LOS, observed OSM edge, timestamps, model status; chỉ nâng hạng camera có chứng cứ. Không bật toàn cục để làm demo. | Có ít nhất một camera được phép + verified đúng edge, test tác động route; unverified chỉ xem ảnh. |
| C09 | `data/models/model_manifest.json`; `scripts/ml/prepare_flood_dataset.py` | Báo `VALIDATED_HCMC_ROAD_FLOOD` dù script train tạo ảnh/mask tổng hợp. IoU/F1 cũ không chứng minh CCTV real generalization. | Đổi nhãn `EXPERIMENTAL_SYNTHETIC` đúng chứng cứ; giữ checksum model; train/finetune trên ảnh có quyền + mask thật; group/site split, hard negatives; report test độc lập & parity ONNX. | Có dataset card/license, sample count/split, IoU/F1 trên ảnh thật, failure gallery; không tuyên bố độ sâu nước từ pixel. |
| C10 | `vision.py` `FloodSegmenter` & `VehicleDetector` | Model status `VERIFIED_ONNX_INFERENCE` chứng minh file/hash/schema, chưa chứng minh mô hình chính xác ngoài thực địa. | Tách `ARTIFACT_VERIFIED`, `INFERENCE_OK`, `FIELD_VALIDATED`, `ROUTING_ELIGIBLE`; model registry và metrics đúng tập. | UI/API model status phân biệt kỹ thuật vs hiện trường; error frames/mask không làm hệ thống crash. |
| C11 | `frontend/src/components/SpatialDashboard.tsx` | WebSocket chỉ cập nhật state cảnh báo theo `type/source` nhất định, chưa tự kiểm soát re-route; do B01 cảnh báo có thể chưa tới. | Khi nhận hazard liên quan current route, debounce+cooldown+user confirm (nếu dẫn đường) rồi recompute; tính route revision ID; ignore stale/out of corridor. | Alert có bằng chứng gây cảnh báo và đề xuất route mới, không reroute liên tục. |
| C12 | `frontend/src/components/MapContainer.tsx` | Có traffic color, flood overlay nhưng UI có thể khiến UNKNOWN bị hiểu là thông thoáng nếu legend/source không khớp. | Legend 4 màu (red/yellow/green/gray) + flood pattern riêng, độ phủ và timestamps, segment popup source; test visual UX. | Fixture 4 trạng thái hiển thị đúng và không chồng line hazard. |

## C. P1 — ổn định runtime, bảo mật, hiệu năng, Cloud readiness

| ID | Nơi | Rủi ro / thiếu | Sửa / tiêu chuẩn hoàn tất |
|---|---|---|---|
| R01 | `backend/app/main.py:lifespan` | Camera, vision, news, weather worker được tạo trong **mỗi** process web, dẫn tới lặp scheduler khi scale. | Worker riêng (process/Cloud Run Job/Redis leases), web stateless; kiểm tra start/stop, graceful shutdown, duplicate lock. |
| R02 | `background_camera_fetch_worker_loop` + `config.py` | `CAMERA_INGESTION_ENABLED` không xuất hiện trong phép `can_scrape = PERMITTED or VIEW_ONLY`; chỉ VIEW_ONLY=True cũng có thể chạy scheduler tải ảnh. | Thực thi rõ cờ `INGESTION_ENABLED`, `VIEW_ONLY`, `PERMITTED`; mô tả quyền từng hoạt động, test disabled→zero outbound. |
| R03 | Camera batch | 796 camera × interval 30s / batch 16 lý thuyết ~25 phút chưa kể timeout/callback; route priority có thể bị nghẽn bởi sweep. | Queue priority active corridor, per-provider concurrency cap, dedupe SHA, negative cache, retry/backoff/TTL, metrics throughput/backlog/recency; không tải toàn bộ khi route. |
| R04 | Camera freshness | Timestamp HTTP fetch không tự chứng minh lúc camera chụp. | Lưu riêng `captured_at`, `retrieved_at`, `analyzed_at`, source_last_modified; missing capture → UNKNOWN, chặn stale route evidence. |
| R05 | `backend/app/db/session.py:init_db` | `create_all` không xử lý schema migration khi thay đổi ORM, DB PostGIS cần extensions và index ổn định. | Alembic migration/versioning, PostGIS preflight, seed reproducible, rollback/backup, spatial query EXPLAIN; không reset database phá dữ liệu. |
| R06 | `docker-compose.yml`, `backend/app/core/config.py` | Hardcoded DB password, public host port PostGIS/Redis, dev defaults; không phù hợp production. | Secret Manager/runtime env, network private, no public DB/Redis ports in production, restrict CORS, token auth, least privilege. |
| R07 | `backend/app/main.py` API routes | Chưa có xác minh rate limiting toàn diện. Endpoint camera refresh/geocoding/route có thể bị spam. | Input validation, request quota/user/IP, max body/request time, parameter limits and throttled external API; negative path tests. |
| R08 | `frontend/src/hooks/useLiveObservations.ts` | Poll toàn danh mục camera + 4 API mỗi 30s cho mỗi client, không bbox/page; tăng network và render load. | Viewport filter/page, conditional fetch, SWR/React Query dedupe, ETag, abort controller, visibility-aware refresh, server aggregation. |
| R09 | `frontend/src/services/api.ts` & Next.js proxy | Mặc định REST dùng same-origin proxy; WS riêng không qua proxy, local/Cloud khác nhau. | Env example theo dev/docker/cloud, explicit `wss://`; browser network and CORS smoke test. |
| R10 | `backend/app/main.py:health`, Docker | Health phụ thuộc PostGIS/Redis/OSRM, `backend` startup phụ thuộc OSRM. Khi graph thiếu toàn bộ FE có thể bị block. | Preflight script check PBF/OSRM graph; `/live` process and `/ready` dependencies, health state `degraded` vs `unavailable`, fallback UI; bảo đảm server vẫn báo lỗi có cấu trúc. |
| R11 | `scripts/setup_osrm_hcm.sh` | Graph vùng Việt Nam lớn, download/compile yêu cầu tài nguyên; không được chờ build từ mỗi web deploy. | Build offline once, checksum/license metadata, version graph, persist mount; benchmark CPU/RAM/disk; provider-based fallback nếu cloud nhỏ. |
| R12 | `.github/workflows/ci.yml` (đã cập nhật PR #16) | Giờ CI cấu hình chạy cả `pytest backend/tests/ -v` với PostGIS/Redis, nhưng **chưa có kết quả PASS** và không chạy OSRM. E2E Playwright chưa có gate. `assign_camera_districts_postgis.py || true` còn che lỗi. | Tách unit test độc lập khỏi live/OSRM/permission test, marker chính xác, thêm Playwright smoke, security checks, typecheck/build, branch protections; **không** làm xanh bằng `|| true` khi bước bắt buộc fail. |
| R13 | `.github/workflows/docker-image.yml`, `.github/workflows/cd.yml`, Dockerfile | Workflow mới ở PR #16 đã đổi GHCR image names; CI chỉ build/push; `cd.yml` **chưa deploy** lên cloud dù tên là CD. Frontend Dockerfile dùng `ENV AUTH_SECRET` build placeholder và có security warning. | Kiểm tra run mới, GHCR package access, không đưa real secrets vào Docker build, runtime secrets; thêm bước deploy thực riêng (chỉ sau phê duyệt chi phí), health check và rollback. |
| R14 | `frontend/src/auth.ts` & API proxy | `signIn` có thể trả true dù sync user thất bại; token.id có thể không trùng DB; backend vẫn tin header tùy ý. | Fail/safe login state; server-side verified identity, retry idempotent sync, auth integration suite. |
| R15 | API + telemetry | Thiếu trace end-to-end từ provider→risk→route→UI và failure budget. | JSON logs request_id/route_id/traffic_source/coverage/cache hit/latency/worker backlog; sanitized logs, metrics p50/p95/p99, alert on failure. |
| R16 | README và docs | `README.md` là tài liệu phiên bản repo cũ tham chiếu ngày 24/10; `ACCEPTANCE_EVIDENCE.md` có số đo hệ thống cũ. | Viết README Hackathon đúng SHA, commands, owner/module/status, log evidence **đo lại** trên repo mới; không dùng kết quả cũ như nghiệm thu hiện tại. |

## D. Điều kiện nghiệm thu theo lớp (gates) — làm tuần tự

### G0 — Git/Secrets/Worktree
- Chốt SHA baseline, tạo branch P0 riêng, PR review; không merge khi CI đỏ.
- `git status -sb`, `git ls-files | grep -E '(^|/)\.env(\.|$)'` kiểm tra không có secrets được track; dùng private channels cấp token, rotate secrets đã lộ.

### G1 — Bootstrap
1. `bash scripts/setup_osrm_hcm.sh` trên máy đủ RAM/disk (chỉ nếu chưa có graph); kiểm tra file MLD.
2. `docker compose config` → `docker compose up -d --build` → `docker compose ps` → log từng service.
3. `curl -fsS http://localhost:8000/api/v1/health` và `curl .../api/v1/models/status`.
4. Kiểm tra PBF version, PostGIS `road_segments`, `road_edges`, `historical_flood_points`, `traffic_cameras`, extension PostGIS; không lấy số từ README làm kết quả thật.

### G2 — Typed contracts + auth + WebSocket
- Sửa B01, B02, B08 trước; tests positive/negative, browser WS, expired/duplicated alert; không log headers/token.

### G3 — Risk/Traffic/ETA
- Sửa B03–B07 và C01–C07, thiết kế 4 fixtures: no data→UNKNOWN; closure→avoid; camera flood-only→critical; congested not flood.
- 3 tuyến A/B thực tại HCMC, kiểm tra OSRM geometry/distance, traffic provider match/coverage/ETA và fallback đúng nguồn.

### G4 — Vision/CCTV
- Model ONNX CPU smoke, segmentation mask, malformed image/placeholder, confidence and QA; train real CCTV holdout; camera eligibility gate, license, timestamp; không giả lập live.

### G5 — Performance
- Mốc bắt đầu đo đề xuất (chưa phải KPI đã đạt): 30 concurrent route lookups, request success >= 99% trên môi trường ổn định với provider mocks riêng test, p95 API < 3s cho cached/no-extra-IO, model inference p95 theo CPU thực. Nếu live provider chậm phải report riêng; số cần đo, không bịa.
- Benchmark CPU/RAM backend, OSRM, Redis cache hits, per-journey TomTom call count, frontend FPS mobile.

### G6 — Continuous delivery
- PR #16 đã cấu hình full backend pytest + PostGIS/Redis và Docker validate, **nhưng chưa có PASS**. Tách isolated/live suite, thêm Playwright smoke, GHCR images success, artifact SHA, scan và security; deploy trên staging secrets/runtime URLs; không đánh dấu production khi chỉ có image push.

### G7 — Cloud / production smoke
- Cloud Run FE/BE (hoặc nền tảng phù hợp), tách OSRM graph, worker và database bền vững; HTTPS/WSS, secret manager, auth callback; backup/rollback, budget alerts; cần quyền cloud và phê duyệt chi phí trước khi tạo tài nguyên.

## E. Phân chia công việc 6 người

| Vai trò | Ticket được giao | Merge gate |
|---|---|---|
| Lead / Integration | B03–B07, C04, API acceptance, routing scenarios | G3 |
| BE/Auth | B01 B02, R07 R14, DB versions | G2 |
| Traffic/GIS | C01–C07, G1 graph checks, TomTom exact-match | G3 |
| ML/CV + Data | C08–C10, R02–R04, model card/real holdout | G4 |
| FE/Map | B08, C11 C12, R08 R09, modal/WS E2E | G2/G3 |
| DevOps/QA | B09, R01 R05 R06 R10–R13 R15 R16, CI & cloud | G1/G5/G6/G7 |

## F. Definition of Done cho mỗi PR

1. Problem statement + root cause + file/line + intended behavior.
2. Test thể hiện lỗi cũ thất bại và bản mới pass (không chỉ thay assertion).
3. Security/permission/provenance/fallback được kiểm chứng.
4. Log command CI thực tế gắn commit SHA, test suite count và lý do skip.
5. Demo/traces nếu liên quan FE/WS/routing; không sử dụng dữ liệu mô phỏng như live.
6. Review bởi một người không phải tác giả; không force-push main, không tự merge khi gate đỏ.

## G. Prompt ngắn cho coding agent

> Hãy đọc **toàn bộ tài liệu này** và `README.md`, kiểm tra lại `main` hiện tại trước khi code. Làm việc trên nhánh tính năng riêng. Bắt đầu với G0, G1 và B01/B02/B03/B04/B06. Không rewrite UI/Design System/Map đã hoạt động. Mỗi ticket phải có test hồi quy, runbook và trạng thái CODED/TESTED/LIVE-VERIFIED/BLOCKED; không tuyên bố hoàn tất khi chỉ tạo file. Chỉ chạy các integration/live tests khi có quyền và credentials. Không thay `UNKNOWN` bằng `SAFE`, không ngụy tạo số liệu camera/TomTom hoặc độ chính xác model. Sau mỗi gate tạo PR và báo cáo rõ kết quả, không tự merge `main`.

---

**Giới hạn kiểm toán:** Những lỗi nêu trong nhóm BLOCKER phần lớn được xác nhận theo code; các mục liên quan nhà cung cấp API, OSM graph, Google Cloud, độ phủ camera, kết quả unit/integration test chỉ có thể nghiệm thu bằng môi trường thực. Cần tái kiểm tra commit SHA vì repo có nhiều merge liên tiếp trong thời gian thi.

### Delta sau PR #16 (15:38 ICT)

- Merge #16 thêm `.github/workflows/cd.yml`, viết lại `ci.yml` và `docker-image.yml`; **không có thay đổi** ở `risk_engine.py`, `routing.py`, `main.py` và các file FE trong PR này.
- `ci.yml`: chạy toàn bộ pytest thay vì chỉ hai test; phân nhóm live test nếu cần OSRM/nguồn camera, và bỏ cách nuốt lỗi với `|| true` trong bước seed bắt buộc.
- `cd.yml`: chỉ build/push image, **chưa chạy ứng dụng trên Google Cloud/AWS**; không coi đây là triển khai production.
- Docker Image CI run `42356359877` trên commit trung gian `014289676` đã **SUCCESS**. Run trên `main` hiện tại `9495e84e` (`42356366651`) vẫn đang chạy khi kiểm tra; không dùng kết quả commit trung gian để khẳng định HEAD đã PASS. CI full pytest chưa có bằng chứng kết quả xanh trên HEAD.
