# Kịch bản demo3phút cho BGK

## 0:00–0:35 — Bài toán và phạm vi

Mở `/benchmark`: “SafePath hỗ trợ xem camera và chọn đường dựa trên nguồn có thời gian, vị trí và quyền sử dụng. Trang này đọc kết quả do lệnh benchmark vừa chạy, không có con số viết cố định trong giao diện.” Chỉ vào timestamp, model hash và trạng thái LIMITED/NOT EVALUATED.

## 0:35–1:20 — AI thật và hiệu năng

Mở bảng model và biểu đồ độ trễ: “Hai model ONNX đúng hash đã chạy inference trên ảnh camera có sẵn. Chúng tôi đo riêng model-only và pipeline có đọc/kiểm định ảnh, công bố warmup, số vòng, phần cứng/provider. FPS một model không phải throughput cả hệ thống.” Đọc số thực tế từ bundle đang mở, không đọc số lịch sử trong tài liệu cũ. Nếu node providerCPU thì nóiCPU, không nóiAppleNeuralEngine chỉ vì máyM2.

## 1:20–2:05 — Chứng cứ đúng với giới hạn

“Chúng tôi chưa có tập test hiện trường độc lập được gán nhãn để công bố IoU/mAP. Vì vậy hai phần accuracy ghi NOT EVALUATED. Bộ công cụ đã tính được globalIoU/per-imageIoU, Dice/PR, AP nhiều ngưỡng, confusion và ảnh lỗi khi được cấp dataset hợp lệ.” Không trình chiếu ảnh camera chưa có quyền hoặc ảnh chưa blur dữ liệu riêng tư.

## 2:05–2:40 — Routing, camera và tải

Chỉ vào kịch bản routing: “Đây là kiểm thử ràng buộc: ảnh cũ/không đúng edge không thành evidence, mọi tuyến nguy hiểm không được gắn đề xuất an toàn. Tỷ lệ testpass không phải độ chính xác AI ngoài đường.” Camera registry khác camera đang có ảnh; sample3không đại diện796. Tải k6 chạy local riêng với provider bên ngoài tắt, nêu concurrency và lỗi thật, không suy ra SLAproduction.

## 2:40–3:00 — Tái lập

Tải JSON/CSV/methodology, mở câu lệnh full từ README benchmark. “Bất kỳ ai có đúng mã nguồn, weights, quyền dữ liệu và dataset manifest có thể chạy lại. Phần chưa đủ điều kiện vẫn ghi rõ, không biến thiếu dữ liệu thành thành công.”

## Câu có thể nói

- Model weights đúng SHA-256 và inferenceONNX thật đã được kiểm tra trong lượt chạy này, nếu JSON ghi verifiedhash.
- Đây là latency đo trên máy cụ thể, với cấu hình/provider và scope được công bố.
- Các kịch bản có expected outcome độc lập đã được thực thi; có log command/exitcode.
- Chưa biết/không đo được được báo cáo rõ ràng thay vì điền0hoặc100%.

## Không được khẳng định

- “AI chính xácX%” khi chưa có GT độc lập; mAP/IoU không thể suy từ count tăng.
- “Rain/nightPASSED” hoặc “mọi camera live” nếu không có subgroup/chu kỳ đo.
- “An toàn tuyệt đối”, “ETA ngangGoogle”, “không có ảnh nghĩa là không ngập”.
- “Chạy GPU/ANE” dựa vào availableprovider thay vì nodeexecution/hardwareevidence.
- “Chịu50/1000user production” từ burst25VU local hoặc modelFPS.

## Trả lời câu hỏi khó

**Accuracy/dataset?** Chưa có independentlabelledfieldtest; số cũ thuộc synthetic/controlled data và không được dùng làm kết quả mới. Đã có schema/toolmetric; cần nhãn độc lập có quyền dùng.

**Bias?** Ảnh mẫu local chưa đại diện phân bố camera/ngàyđêm/mưa. Dataset cần phân tầng và tách nguồn/camera/scene/ngày để giảm leakage; chưa có corpus huấn luyện ngoài thì không xác minh hoàn toàn độc lập.

**Benchmark đáng tin?** Có SHAmodel, commit/diff, thời gian, số vòng, rawsamples, công thức và commandlog. Mỗi kết quả nói đúngscope; không gộp lịch sử vào runmới.

**Camera/ngập thực tế?** Chỉ phản ánh ảnh/vùngquan sát; segmentationnước không đo độsâucm và một camera không xác nhận cả tuyến. Capturetimeunknown khác retrievaltime.

**Model baseline cải thiện chưa?** Chỉ so khi cùng dataset/threshold/provenance; chưa có labels thì count/latency không chứng minh accuracy cải thiện.
