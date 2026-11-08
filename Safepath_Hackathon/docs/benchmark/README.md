# Chạy benchmark SafePath

Bộ benchmark đo lại trên mã nguồn/model hiện tại. Không có nhãn độc lập thì không có accuracy. Không tự tải dataset, không huấn luyện/ghi đè weights, không gọi Google trả phí.

## macOS / Linux

Từ repo root, dùng Python3.12 và môi trường dự án:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/run_hackathon_benchmark.py --quick --offline --publish
```

## Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/run_hackathon_benchmark.py --quick --offline --publish
```

Không cần PyTorch để đo ONNX. Cần k6 nếu chạy tải: cài Grafana k6 bằng phương thức chính thức phù hợp hệ điều hành, rồi kiểm tra `k6 version`. CoreML chỉ khi ONNX Runtime trên Mac có provider này; CUDA chỉ khi runtime/phần cứng hỗ trợ. CPU là cấu hình benchmark mặc định có thể tái lập,2thread; không sửa cấu hình production.

## Một lệnh tái lập

```sh
python scripts/run_hackathon_benchmark.py --full --publish
```

Lệnh full đo100vòng model-only ×3session mỗi model, cộng20 mẫu pipeline/session; phần load/routing tích hợp cần một **QA database context riêng**. Mặc định thiếu context sẽ ghi BLOCKED thay vì thử tải app đang dùng:

```sh
python scripts/run_hackathon_benchmark.py --full --qa-context /private/safepath-qa-context.json --publish
```

Context là JSON mode0600 với DATABASE_URL (tên DB bắt đầu safepath_readiness_qa_ hoặc safepath_qa_), database_name, REDIS_URL chỉ DB15, OSRM_BASE_URL trỏ OSRM local, APP_ENV=development, TESTING=true. DB đã migrate/seed phải được tạo riêng; không điền DB production. Không đưa file context/DSN vào Git. Runner tự tạo backend local tạm chỉ bind127.0.0.1, tắt worker/provider bên ngoài/cameraAI, dừng process sau tải. Không dùng chế độ offline để tuyên bố database/network đã chạy.

- `--quick`:10vòng,1session,2warmup; tải1VU nếu có context.
- `--full`:100vòng model-only,20mẫu mỗi loại pipeline,3session,5warmup; k6 một iteration/VU theo1/10/25, dừng khi lỗi/timeout/ngưỡng không đạt.50VU chưa chạy trên máy RAM hạn chế.
- `--offline`:không gọi API/DB; vẫn chạy ONNX thật trên ảnh hợp lệ có sẵn và kịch bản unit. Không thay ảnh thật bằng synthetic tensor.
- `--output <path>`:thư mục kết quả riêng. Thư mục mặc định `reports/hackathon-benchmark/`.
- `--provider CPUExecutionProvider|CoreMLExecutionProvider|CUDAExecutionProvider`:cấu hình đo rõ ràng; JSON ghi provider thực tế thực thi node từ ORT profiling. Tên CoreML không chứng minh ANE/GPU nào thực sự xử lý.
- `--flood-dataset <manifest>`/`--vehicle-dataset <manifest>`:chỉ cung cấp sau khi làm đúng [hướng dẫn gán nhãn](DATASET_ANNOTATION.md), có license/provenance, split và nhãn thật.
- `--local-api http://127.0.0.1:8000`:chỉ đọc registry/summary và tối đa3 ảnh nguồn trên local; có thể dẫn đến tối đa3fetch thông thường. Không sweep796camera.
- `--publish`:chỉ chép allowlist JSON/CSV/Markdown/chart sang `frontend/public/benchmark/`. Không copy logs/XML/ảnh camera/ảnh private. Không có nút public chạy benchmark.

## Dashboard

```sh
cd frontend
npm ci
npm run dev
```

Mở http://localhost:3000/benchmark. Với Docker, build lại frontend sau `--publish` rồi mở cùng URL. Dashboard có thể trình chiếu offline từ static bundle: Next server chỉ đọc tài nguyên local, không cần API bên ngoài cho dữ liệu benchmark; nên mở thử ở chế độ offline trước khi thi. Báo cáo thiếu/lỗi schema hiển thị NOT EVALUATED.

Các log dưới output có thể chứa lỗi local, chỉ phục vụ vận hành, không public. CSV/JSON có SHA/metadata và rawtimings; không có secrets/ảnh. Hãy lưu snapshot mã nguồn dirty, diff, weights hash và dataset manifest cùng kết quả: chỉ commitSHA không đủ khi chưa commit thay đổi.

## Dataset chưa có

Không tạo sốaccuracy từ số xe đếm tăng hoặc tỷ lệ pixel nước. Chuẩn bị nhãn bằng công cụ bất kỳ như CVAT/LabelStudio hoặc editor mask/box, export theo manifest [DATASET_ANNOTATION.md](DATASET_ANNOTATION.md). Tách camera/scene/ngày giữa train/val/test; kiểm tra duplicatehash và nguồn train nếu có. Không tự coi data synthetic là hiện trường độc lập.

`--compare-baseline` cùng `--vehicle-dataset` bật single-frame VGG16-SSD đối chiếu production tiling trên cùng GT/threshold. CSV giữ từng run/level bằng đường dẫn có chỉ số mảng. Benchmark bật ORT profiling trong lúc đo để ghi nodeprovider; có tracing overhead. `route_search_timeout_rate` nhận mã1050(requesttimeout)/1211(dialtimeout) theo [k6 Error Codes](https://grafana.com/docs/k6/latest/javascript-api/error-codes/).

Khi có nhãn và quyền trình chiếu ảnh, đặt `allow_public_examples:true` trong manifest. Runner chỉ công bố đúng các PNG comparison được tạo từ lượt đó; dashboard cần đồng thời cờ quyền và tên artifact khớp allowlist. Các example cũ thuộc allowlist được dọn khỏi bundle khi lượt mới không được phép xuất ảnh. Ảnh gốc không bao giờ tự được copy thành thư mục public.

Lưu ý phép đo đầy đủ hiện có dùng CPUExecutionProvider,100model-onlysamples/session và20pipeline-file/session. Các node thực thi đều được kiểm tra từ profile. Không suy ra CoreML/ANE/GPU đã chạy nếu không có lượt đo provider đó. Tracing overhead và p99 với số mẫu nhỏ được ghi trong limitations.

Bộ JSON còn có commands.json ghi lệnh/exitcode của lượt chạy. Exitcode1 là đúng khi loadFAILED; báo cáo vẫn được tạo. Đừng coi exitcode0 ở chế độ offline là bằng chứng camera/network đã được nghiệm thu.
