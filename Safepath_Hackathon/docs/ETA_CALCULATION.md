# ETA theo tốc độ giao thông — 08/11/2026

ETA dùng thời gian trên đúng phần đường có số đo; phần còn thiếu được ghi rõ là ước tính. Không chỉnh hệ số để khớp một con số Google Maps đơn lẻ.

## Công thức và nguồn

Với từng chặng OSRM:

- Phần có tốc độ phù hợp: `thời gian = quãng đường được phủ / tốc độ hiện tại`. Tốc độ nhà cung cấp thay thế thời gian nền trên phần này.
- Phần chưa có tốc độ: dùng thời gian OSRM của chặng, nhân tỷ lệ phần chưa được phủ và hệ số khung giờ đang có. Nếu thiếu thời gian từng chặng, phân bổ thời gian tổng theo khoảng cách. Chỉ khi OSRM không cung cấp thời gian hợp lệ mới dùng ước tính theo khoảng cách.
- Cộng thời gian các phần để ra ETA. Không cộng thêm hệ số ô tô1.25, đèn đỏ suy đoán theo mỗi550m, số lần rẽ, phạt do cảnh báo nguy hiểm/mưa hoặc ép tốc độ vào khoảng4.8–35km/h.

Ví dụ kiểm thử, không phải số đo đường thực tế:1km được phủ đầy đủ với tốc độ60km/h cho ETA60giây;30km/h cho120giây.1km ở1km/h vẫn3600giây, không bị rút ngắn do chặn tốc độ tối thiểu.500m ở60km/h cộng với500m còn thiếu dùng thời gian nền tương ứng, không cộng thời gian toàn chặng hai lần.

Tốc độ, độ mới, confidence và matching phải hợp lệ: tốc độ hữu hạn trong(0,160]km/h, confidence[0.3,1], tuổi dữ liệu[0,300]giây, trạng thái dòng xe phù hợp, có chiều dài được phủ rõ ràng. Mật độ xe từ ảnh không tự trở thành tốc độ đo được. Đường đóng hoặc tốc độ0 giữ cảnh báo nguy hiểm nhưng không được coi là dữ liệu ETA có thể đi qua. ETA số trên phương án nguy hiểm chỉ là tham khảo; trạng thái đóng/nguy hiểm và chính sách xếp hạng vẫn tách riêng.

## Độ phủ provider

TomTom/HERE chỉ phủ phần polyline cùng hướng trong hành lang12m, chênh hướng tối đa30°. Không suy rộng số đo giữa đường ra toàn chặng. Khoảng hở giữa các link HERE không được nối giả. Không dùng kết quả thiếu geometry; HERE không chọn bừa bản ghi đầu khi chưa khớp. Trùng geometry được loại trong từng lần đi qua; tuyến vòng/lặp vẫn tính đúng các lần đi qua cùng đoạn.

Đơn vị TomTom dùng KMPH; HERE trả m/s, chuyển sang km/h. Các dòng không có confidence hợp lệ bị loại. Cache phải có thời gian timezone-aware, không ở tương lai và còn TTL. Bản cache cũ thiếu timestamp không được gán lại thời gian hiện tại. Tuổi dữ liệu mới lấy được tính ở lúc hoàn tất matching để tránh số âm khi request kéo dài. Timestamp này là lúc nhận dữ liệu, không phải xác nhận thời điểm quan sát gốc của provider.

TomTom có thể dịch geometry theo mức zoom; ngưỡng12m bảo thủ có thể giảm độ phủ và chuyển sang ước tính. Matching vị trí không chứng minh cùng tầng cầu hoặc quyền sử dụng camera. Không nâng các permission flags của camera.

## Phương tiện và mức tin cậy

- Ô tô và xe máy dùng tốc độ trên đoạn có dữ liệu; không tự nhân chậm ô tô hoặc tự làm xe máy nhanh hơn.
- Graph OSRM hiện dùng profile ô tô. Phần ước tính cho xe máy chưa phải graph/ETA xe máy được kiểm định riêng; không cam kết trùng tuyến hoặc thời gian với Google Maps.
- Đi bộ dùng4.8km/h theo khoảng cách, không lấy tốc độ xe hoặc tự nhận có dữ liệu giao thông live. Tuyến đường bộ chuyên dụng vẫn là giới hạn graph hiện tại.
- `eta_breakdown.confidence` là mức hỗ trợ theo confidence nguồn × tỷ lệ quãng đường được phủ; không phải xác suất ETA chính xác. Chưa có dataset chuyến đi thực để khẳng định sai số trung bình.
- Hệ số khung giờ cho phần thiếu dữ liệu vẫn là ước tính cũ chưa được hiệu chuẩn độc lập; giao diện ghi rõ phần nào còn ước tính. Không nhân hệ số này vào phần có tốc độ.

## Contract

API hiện có được giữ. Bổ sung trường tùy chọn `RouteSegmentRisk.osrm_duration_seconds` để giữ thời gian từng chặng. `SegmentTrafficFlow.observed_length_meters` là chiều dài provider thực sự phủ; assembler truyền sang `traffic_observed_length_meters`.

`estimated_duration_seconds` luôn có giá trị ước tính; `duration_in_traffic_seconds`/`traffic_adjusted_eta_seconds` là null khi không có tốc độ đủ điều kiện. `is_live_traffic` và `traffic_coverage_ratio` chỉ tính tốc độ được chấp nhận, không đếm mật độ ảnh. `eta_source` phân biệt `OSRM_TIME_OF_DAY_ESTIMATE_*`, provider `MEASURED_SPEED_PARTIAL/FULL` và `WALKING_DISTANCE_ESTIMATE`. `traffic_eta_status` giữ các nhóm BASE_OSRM_NO_TRAFFIC / TRAFFIC_ADJUSTED / TRAFFIC_VERIFIED_FREE_FLOW.

Breakdown: thời gian nền gồm phần free-flow của đoạn có tốc độ và OSRM của phần thiếu; delay gồm chênh lệch dòng xe + ước tính khung giờ trên phần thiếu. Tổng nền+delay khớp thời gian hiển thị sau làm tròn. Các trường delay đèn đỏ/rẽ/mưa cũ giữ0 để tương thích. Raw OSRM duration được giữ riêng; Redis chỉ cache route thô, ETA tính lại mỗi request nên không tái sử dụng kết quả ETA cũ.

## Kiểm thử và đối chiếu

`test_eta_speed_priority.py`: tốc độ thay thời gian nền, partial coverage, bước OSRM khác tốc độ, đầy đủ dữ liệu không bị nhân giờ cao điểm, không cắt ngắn ùn tắc nặng, không biến camera density thành live ETA, zero/closed/stale/low confidence và tổng breakdown.

`test_traffic_flow_coverage.py`: phủ một phần, đường song song/ngược hướng, thiếu geometry, đường cong/vertex thưa, candidate HERE không rõ ràng, cache timestamp, độ mới sau HTTP và tuyến lặp. Các test dùng fixture được đánh dấu; production không tạo dữ liệu giả.

Các range ETA cũ và giả định xe máy luôn nhanh hơn ô tô đã được thay bằng kiểm tra công thức/quyền nguồn cụ thể, thay vì coi các range đặt tay là ground truth.

Một tuyến người dùng báo khoảng13km, SafePath43phút/Google30phút chỉ là ví dụ phát hiện bias; cần so sánh cùng tọa độ, phương tiện, lộ trình và thời điểm trên nhiều chuyến đi để nghiệm thu độ chính xác. Dữ liệu giao thông trước/sau cập nhật có thể thay đổi, nên đối chiếu trực tiếp một lần không tách được hoàn toàn ảnh hưởng công thức và nguồn dữ liệu.

Nguồn chính thức: [TomTom Flow Segment Data](https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/flow-segment-data), [HERE Flow](https://docs.here.com/traffic-api/docs/flow). Không tích hợp hoặc gọi thêm Google API trả phí trong thay đổi này.

## Kết quả kiểm chứng lần sửa này

- Regression backend: **522 PASS,15 SKIP**.14 test live là opt-in, một test legacy cần PyTorch chưa cài. Đã sửa bốn bài test assembly/contract vốn vô tình phụ thuộc OSRM đang bật: dùng fixture transport riêng cho unit, vẫn giữ test OSRM/PostGIS live riêng. Không đổi production transport thành mock.
- Speed-priority/snapshot/ETA scenarios:37 PASS. Provider geometry/freshness/repeated traversal:24 PASS. Review độc lập đã xác nhận sửa tuổi dữ liệu âm và đếm thiếu tuyến lặp; không còn HIGH/MEDIUM trong phạm vi review này.
- Frontend lint/typecheck/unit12 PASS; Docker backend/frontend build PASS. Browser route copy/coverage/mobile:9 PASS ở lượt cuối11.9s; OSRM/API live14 PASS và graph thực tế5 PASS (chỉ đọc). Cả5 container local healthy.
- Cùng geometry một lộ trình local11.963km: bản cũ45.9phút, bản mới26.8phút, tốc độ hợp lệ phủ86% quãng đường. Đây là số trả từ API ở hai thời điểm khác nhau, không phải benchmark ground truth hoặc chứng minh sai số so với Google. Mẫu request chứa tọa độ được giữ riêng ngoài Git; báo cáo không công bố vị trí người dùng.
- Không commit/push và không triển khai server production. Local stack được cập nhật, không thay dữ liệu graph/camera permission hay migration DB.
