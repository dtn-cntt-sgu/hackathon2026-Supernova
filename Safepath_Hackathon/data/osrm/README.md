# OSRM dữ liệu đường Việt Nam cho TP.HCM

Nguồn: [Geofabrik Vietnam](https://download.geofabrik.de/asia/vietnam.html), OpenStreetMap contributors (ODbL). `scripts/setup_osrm_hcm.sh` tải `vietnam-latest.osm.pbf` và file MD5 cùng tên qua HTTPS, kiểm checksum, rồi dùng **nguyên extract Việt Nam**. Không cắt ranh giới nên đường liên quận, đường đi qua ranh giới hành chính và turn restriction không bị mất do phép cắt.

## Yêu cầu máy

- Docker Engine/Compose, curl, `md5sum` hoặc `md5`.
- Dung lượng trống: tối thiểu khoảng **15 GB**, khuyến nghị **30 GB** cho PBF, file graph trung gian, image và build. Dung lượng thực tế biến động theo ngày cập nhật OSM.
- Docker VM: khuyến nghị **16 GB RAM**, **4 CPU** trở lên cho nguyên extract Việt Nam. 8 GB có thể OOM trong extract/partition; khi đó nâng giới hạn VM trước khi chạy lại. Việc chạy trên host ARM64 với image x86_64 có thể chậm do emulation.
- PBF Geofabrik hiện cỡ vài trăm MB; graph đã trích xuất lớn hơn nhiều. Script sẽ dừng nếu checksum sai hoặc thiếu output MLD.

## Thiết lập

```bash
scripts/setup_osrm_hcm.sh
docker compose up -d osrm
docker compose ps
docker compose logs --tail=100 osrm
scripts/check_osrm.sh
```

Script dùng `/opt/car.lua` với `osrm-extract`, `osrm-partition`, `osrm-customize`; server dùng `osrm-routed --algorithm mld`. Các file `vietnam-latest.osrm*` nằm trong `data/osrm`, mount read-only vào `/data` của container. Không dùng profile xe máy: ETA/luật đường là cho ô tô.

Từ máy host: `http://localhost:5000`. Từ container cùng Compose network: `http://osrm:5000` (đặt `OSRM_BASE_URL` theo nơi backend chạy). `alternatives=3` chỉ yêu cầu tối đa 3 tuyến phụ, OSRM có thể trả ít hơn.

Nếu host port 5000 bị chiếm, dùng `OSRM_HOST_PORT=5001 docker compose up -d osrm`, đặt `OSRM_BASE_URL=http://localhost:5001` cho backend host và `OSRM_HOST_URL=http://localhost:5001` cho script kiểm tra. Không đổi URL nội bộ `http://osrm:5000` của backend trong Compose.

Nguồn tile trên frontend là [OpenFreeMap Liberty](https://openfreemap.org/quick_start/) dùng dữ liệu OpenStreetMap, không cần API key. MapLibre hiển thị attribution do style khai báo. Theo [điều khoản OpenFreeMap](https://openfreemap.org/tos/), dịch vụ công khai không có SLA; không tải tile hàng loạt ngoài giới hạn cho phép. Khi cần bảo đảm vận hành, có thể tự host hoặc dùng dịch vụ có hợp đồng.

## Import PostGIS road Ways (Phase 2)

Sau khi OSRM và PostGIS đã chạy, dùng `scripts/import_osm_roads_hcm.sh`. Script kiểm MD5 của chính PBF dùng bởi OSRM, đọc timestamp trong OSM PBF HeaderBlock, rồi chạy `osm2pgsql` flex với `scripts/osm_roads.lua`. Bảng staging chứa Way trên toàn Việt Nam; SQL chỉ chuyển Way cắt qua envelope dịch vụ TP.HCM (106.30–107.10 E, 10.35–11.20 N) vào `road_segments`, giữ nguyên `way_id`, tags và LineString SRID 4326. `scripts/build_osm_road_edges.sql` chia mỗi Way tại từng cặp đỉnh liên tiếp thành `road_edges` với khóa `(osm_way_id, edge_index)`, chiều dài địa lý thực và GiST. `edge_index` là thứ tự cục bộ trong Way, không phải OSM ID hay OSRM edge ID. Bảng staging bị xóa sau commit. Envelope có vùng đệm, nên vẫn chứa một số Way ở tỉnh lân cận; đây không phải ranh giới hành chính TP.HCM.

```bash
scripts/import_osm_roads_hcm.sh
docker compose exec -T postgis psql -U safepath_user -d safepath_db -c 'SELECT count(*) FROM road_segments WHERE source_url IS NOT NULL;'
OSM_ROAD_LIVE_TESTS=1 OSRM_BASE_URL=http://localhost:5001 .venv/bin/python -m pytest -q backend/tests/test_osm_road_graph_live.py
```

Mỗi dòng `road_segments` là **OSM Way nguyên bản**; `road_edges` là các cặp đỉnh liên tiếp của Way, không phải cạnh turn-by-turn của OSRM. `length_meters` tính bằng `ST_Length(geom::geography)`. GiST trên `geom` và `geom::geography` phục vụ matching mét. `scripts/check_road_graph.sql` là truy vấn kiểm tra ứng viên cho một route WKT thật. Một OSRM step có thể đi qua nhiều cạnh/Way, hai chiều/cầu song song có thể ở gần nhau; API trả tối đa 16 `candidate_road_edges` gần bước nhưng giữ `osm_way_id=null`, `osm_edge_index=null` đến khi có phép khớp xác minh riêng. Không suy OSM Way ID hay edge index từ chỉ số step. Bảng cạnh chưa chứa turn restriction/topology OSRM; chỉ OSRM quyết định tuyến lái xe.

Camera thiếu nguồn GPS và ngày xác minh có `geom=NULL` trong bảng hoạt động. Geometry cũ nằm tại `traffic_camera_unverified_location_archive` để audit. View `camera_road_spatial_candidates` dùng `ST_DWithin(geography, 80m)` với **cạnh** và nhãn `SPATIALLY_NEAR`. Chỉ bản ghi có bằng chứng kiểm tra hướng nhìn, đúng `(osm_way_id, edge_index)` quan sát, bearing/FOV, tầm nhìn không bị vật cản (`line_of_sight_verified`) và thời gian xác minh mới được nhãn `OBSERVED_SEGMENT_VERIFIED`; proximity không chứng minh camera nhìn thấy mặt đường.

Import toàn Việt Nam cần PBF ~320 MB, staging PostGIS khoảng 0,9 GB, bảng HCMC khoảng 0,2 GB và 1,86 triệu cạnh trong lần chạy 23/10/2026; cần thêm chỗ cho index, temporary sort/WAL và graph OSRM. Khuyến nghị Docker VM tối thiểu 8 GB RAM, 4 CPU, 8 GB trống ngoài các yêu cầu OSRM bên trên. Dừng nếu checksum sai hoặc thiếu PBF; không dùng dữ liệu test làm nguồn runtime.
