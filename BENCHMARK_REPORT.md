# Benchmark & Observability Report — Day 14

- **Họ tên:** Phan Trong Hau
- **Ngày chạy:** 25/11/2026 (GMT+7)
- **Môi trường:** Linux x86-64, Intel Core i5-11300H (8 CPU logic), khoảng 16 GB RAM, Python 3.12.3 trên host. Trong stack quan sát, mỗi agent có giới hạn 0,5 CPU và 256 MB RAM.

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Giữ ít nhất 95% request trong mức phản hồi của bài lab |
| Error rate `/ask` | < 2% | Giữ tỷ lệ thành công trên 98%, có khoảng cho tỷ lệ lỗi mock mặc định 1% |
| Accuracy trên golden dataset | ≥ 85% | Ngưỡng CI của lab. Bản v2 sau khi sửa phải đạt 100% và không regression |

Ngưỡng cảnh báo của stack Docker theo cấu hình riêng trong `alert_rules.yml`. Các bảng local dưới đây dùng ngưỡng của `load_test.py`.

## 2. Benchmark hiệu năng local

Mỗi phép đo gửi 300 request vào agent v2 sau khi sửa knowledge base, giữ `MOCK_ERROR_RATE=0.01`. Mỗi mức concurrency dùng cùng `MOCK_SLOW_RATE=0.03`. Các Docker build khác cũng chạy trên host trong một phần phép đo. Đây là kết quả một lần chạy, chưa cô lập nhiễu tài nguyên.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 3.90 | 191.8 | 221.8 | 1706.7 | 1.00% | PASS |
| 10 | 40.00 | 190.0 | 219.3 | 1682.0 | 1.67% | PASS |
| 50 | 91.81 | 228.3 | 546.0 | 1701.2 | 0.67% | FAIL |
| 100 | 74.61 | 405.4 | 2596.0 | 2807.9 | 0.67% | FAIL |

RPS tăng từ 3,90 lên 40,00 khi concurrency tăng từ 1 lên 10, nhưng chỉ lên 91,81 ở mức 50 rồi giảm còn 74,61 ở mức 100. p95 tăng mạnh cùng lúc, phù hợp với việc tranh chấp tài nguyên và chờ xử lý khi nhiều request dồn vào một tiến trình. Phép đo chưa tách chi phí phía client khỏi chi phí phía server.

### Tail latency — concurrency 20

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---:|---:|---:|---:|
| 0 | 192.8 | 219.8 | 234.5 |
| 0.03 | 249.4 | 218.7 | 1705.9 |
| 0.1 | 379.9 | 1698.3 | 1712.3 |

Ở tỷ lệ chậm 3%, p99 tăng từ 234,5 lên 1705,9 ms trong khi p95 gần như giữ nguyên. Ở 10%, nhóm request chậm cũng đi vào p95. Average gộp request chậm với phần lớn request nhanh nên không thể hiện mức ảnh hưởng đến người dùng ở đuôi phân bố.

## 3. Benchmark chất lượng

Tắt lỗi upstream ngẫu nhiên cho cả ba lượt eval. Các số dưới đây lấy từ [reports](reports/).

| Chỉ số | v1 | v2 | v2 sau khi sửa |
|---|---:|---:|---:|
| Accuracy | 4.35% (1/23) | 91.30% (21/23) | 100.00% (23/23) |
| Avg tokens / câu | 57.3 | 109.1 | 113.3 |
| Tổng cost (USD) | 0.000408 | 0.000762 | 0.000787 |
| Cost / câu đúng (USD) | 0.00040755 | 0.00003627 | 0.00003423 |
| p50 latency (ms) | 160.3 | 191.6 | 198.5 |
| Quality gate | FAIL (80%) | PASS (80%) | PASS (100%) |

| Câu sai ở v2 | Keyword thiếu | Thay đổi knowledge base |
|---|---|---|
| `security-02` | token, hết hạn, chữ ký | Thêm giải thích API key và JWT, thời hạn và cách server kiểm chữ ký |
| `scaling-03` | cpu, memory, custom metrics | Thêm giải thích HPA điều chỉnh số pod dựa trên các nguồn metric |

Retrieval tăng token và p50, nhưng giảm chi phí trên mỗi câu đúng nhờ accuracy cao hơn. Lần eval cuối đạt 23/23 và danh sách regression rỗng. [Job CI](.github/workflows/eval.yml) chạy eval cho pull request với ngưỡng 85%. Khi eval trả mã 1, job thất bại. Để chặn merge cần đặt job này làm required status check trong GitHub.

### Đọc metrics

- Counter `http_requests_total` đếm request. Gauge `agent_in_flight_requests` tăng và giảm theo số request đang xử lý. Histogram `http_request_duration_seconds` gom latency vào bucket.
- Label dùng route template và giá trị `unmatched`. Nếu dùng URL thô, nhiều URL lạ khác nhau có thể tạo thêm time series và tăng tải cho Prometheus.
- Đã thêm histogram `agent_question_length_chars` để theo dõi phân bố chiều dài câu hỏi.

## 4. Observability stack

### 4.1. Dashboard và traces

- [Grafana có tải](screenshots/grafana-dashboard.png)
- [Jaeger, trace chậm](screenshots/jaeger-slow-trace.png)
- [Jaeger, trace lỗi](screenshots/jaeger-error-trace.png)

Ở một lần lấy mẫu Prometheus với cửa sổ 1 phút khi Locust đang tăng tải, p95 là **292,5 ms** (xấp xỉ từ histogram), average **230,1 ms**. Ba instance nhận lần lượt **10,91**, **10,13**, **9,95** request/s ở `/ask`, cho thấy Nginx phân tải tương đối đều. Input khoảng **2.285 token/s**, output **1.214 token/s**. Input gồm system prompt, câu hỏi và context retrieval, trong khi output là câu trả lời. Nginx trả **404** với `/metrics` vì endpoint chỉ được Prometheus scrape trực tiếp trong mạng nội bộ.

### 4.2. Thí nghiệm sự cố

`promtool test rules` trả `SUCCESS`. A, B, C dùng cùng một lần cập nhật và D pause thêm một replica trong lần chạy chung để kiểm chứng alert đồng thời. Thời gian là lần đầu thấy trạng thái firing khi hỏi API Prometheus mỗi 2 giây. Do có nhiều biến can thiệp cùng lúc, kết quả chưa định lượng tác động riêng của mỗi biến.

| # | Can thiệp | Alert | Đến lúc phát hiện | Panel |
|---|---|---|---:|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | 78 s | Error rate |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | 138 s | p95 latency |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | 178 s | Cost burn rate |
| D | `docker pause 1 replica` | `AgentInstanceDown` | 42 s | Targets / up |
| E | `AGENT_VERSION=v1` | Không alert firing ở cuối lượt chạy | Không áp dụng | Quality gate |

Thí nghiệm E dùng một replica v1 với 3 users trong 2 phút. Prometheus trả danh sách alert rỗng ở cuối lượt chạy dù eval v1 chỉ đạt 1/23. Hiệu năng HTTP có thể giữ ổn định dù câu trả lời sai. Dùng eval trên golden dataset để chặn release, đồng thời chạy synthetic eval định kỳ trên môi trường thật và theo dõi accuracy theo phiên bản.

[Ảnh Prometheus Alerts](screenshots/prometheus-alert-firing.png)

### 4.3. Đối chiếu trace và log

Trace chậm nhất có đủ span trong log của lần đo một replica là `cf249619057dd24fd4b9c06280486f0b`. Span HTTP mất **1785.3 ms**. Bên trong nó, span `chat mock-llm-small` mất **1763.8 ms (98.8%)**.

```json
{"ts": "2026-11-25T07:45:04.542072+00:00", "level": "INFO", "service": "observable-agent", "instance": "ad2be0e26d24", "event": "http_request", "trace_id": "cf249619057dd24fd4b9c06280486f0b", "span_id": "e85f60dca3cb1210", "request_id": "1f154e6a2a83", "method": "POST", "route": "/ask", "status": 200, "ms": 1784.2}
```

Trace lỗi `96c867ef8a38eec8681977f07fc341d7` trả HTTP 503. Span gọi LLM ghi event `exception` với lỗi upstream mock.

```json
{"ts": "2026-11-25T07:43:54.461604+00:00", "level": "INFO", "service": "observable-agent", "instance": "ad2be0e26d24", "event": "llm_error", "trace_id": "96c867ef8a38eec8681977f07fc341d7", "span_id": "2500561a6aee7462", "request_id": "3a611008be53", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

## 5. Benchmark scaling — Locust headless

Mỗi lượt dùng 100 users, spawn rate 10/s, chạy 2 phút. Các số dưới đây lấy từ hàng `POST /ask` trong [CSV Locust](benchmark-results/).

| Replica | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---:|---:|---:|---:|---:|---:|
| 1 | 60.12 | 190 | 240 | 1700 | 78 |
| 3 | 60.81 | 190 | 220 | 1700 | 74 |

p95 đi từ **240 ms** xuống **220 ms** và p99 giữ ở **1700 ms**. Throughput của hai lượt gần nhau, phù hợp với workload có thời gian nghỉ giữa các lượt gọi và mock LLM có độ trễ riêng. Scale phân tải tốt hơn nhưng mỗi request vẫn chờ mock LLM. Cần thêm một phép đo với tải tăng dần đến bão hòa để xác định trần throughput.

## 6. Kết luận

1. Theo dõi percentile cùng tỷ lệ lỗi giúp thấy ảnh hưởng của các request chậm mà average che khuất.
2. Eval golden dataset và cost trên mỗi câu đúng đo hai khía cạnh mà dashboard HTTP không phản ánh.
3. Truy từ metric sang trace và đối chiếu log bằng `trace_id` giúp xác định bước nào tạo ra độ trễ hoặc lỗi.

Khi triển khai thật, có thể thêm cảnh báo accuracy từ synthetic eval, queue wait time và độ trễ Redis để nhận diện sớm chất lượng suy giảm hoặc hàng đợi quá tải.
