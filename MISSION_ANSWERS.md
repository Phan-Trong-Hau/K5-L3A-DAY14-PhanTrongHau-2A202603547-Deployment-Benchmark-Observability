# Day 14 Lab — Mission Answers

## Part 1 — Localhost vs Production

### 1.1. Các vấn đề trong bản develop

1. API key và thông tin kết nối DB nằm trong mã nguồn, nên dễ bị lộ qua Git.
2. `DEBUG` và `MAX_TOKENS` được gán cố định, khó đổi cấu hình giữa staging và production.
3. `print` ghi câu hỏi, câu trả lời và cả key, vừa lộ dữ liệu vừa khó truy vấn theo trường.
4. Thiếu endpoint health/readiness, nên nền tảng không có tín hiệu riêng để kiểm tra tiến trình và quyết định chuyển tải.
5. Điểm vào dùng `host="localhost"`, port 8000 cố định và chế độ reload, gây khó khi chạy trong container hoặc trên nền tảng cấp cổng qua biến môi trường.
6. Bản mẫu thiếu vòng đời rõ ràng để khởi tạo và giải phóng tài nguyên khi tiến trình dừng.

### 1.2. Kết quả develop

`POST /ask?question=what%20is%20docker` trả về `{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}`. Bản production trả `status=ok` qua `GET /health`.

### 1.3. So sánh

| Hạng mục | Develop | Production | Tác dụng |
|---|---|---|---|
| Cấu hình | Hằng số trong app | Settings đọc env | Tái sử dụng cùng mã nguồn trên các môi trường |
| Secret | Khai báo trong source và ghi ra stdout | Đọc biến môi trường | Tránh đưa secret lên Git |
| Log | Dòng `print` tự do | Log JSON | Dễ lọc theo trường và đưa vào hệ thống log |
| Vòng đời | Chạy với reload | FastAPI lifespan | Có điểm để khởi tạo và dọn tài nguyên |
| Health | Thiếu endpoint riêng | `/health`, `/ready` | Điều phối restart và traffic theo tín hiệu phù hợp |

Ví dụ cụ thể về cấu hình secret: bản develop gán trực tiếp `OPENAI_API_KEY` trong [app.py, dòng 17](01-localhost-vs-production/develop/app.py#L17). Bản production đọc biến môi trường cùng tên trong [config.py, dòng 27](01-localhost-vs-production/production/config.py#L27).

## Part 2 — Docker

### 2.1. Dockerfile cơ bản

1. Base image là `python:3.11`.
2. Working directory là `/app`.
3. Copy `requirements.txt` trước để Docker tái sử dụng layer cài dependencies khi chỉ sửa source.
4. `ENTRYPOINT` chọn chương trình chính. `CMD` cung cấp lệnh mặc định khi không có `ENTRYPOINT`, hoặc cung cấp tham số mặc định cho `ENTRYPOINT` nếu có.

### 2.2–2.4. Chạy container, đo kích thước và Compose

| Image | Kích thước hiển thị trong `docker image ls` |
|---|---:|
| Develop | 1.67 GB |
| Production | 240 MB |

Image production nhỏ hơn khoảng **85,6%** theo dung lượng hiển thị. Builder cài công cụ build và dependencies. Runtime dùng Python slim rồi copy gói Python đã cài và source cần chạy.

```text
Client -> Nginx -> FastAPI agent
                      |-> Redis (cache/session)
                      |-> Qdrant (vector store cho RAG)
```

Compose cấp DNS theo tên service. Nginx chuyển tiếp sang `agent:8000`. Agent nhận URL Redis và Qdrant qua env. `GET /health` qua Nginx trả `200`, `POST /ask` với JSON cũng trả `200` và nội dung mock về Docker. Bản basic dùng query parameter `question`; gửi JSON vào bản basic trả `422`.

Chạy lại bản basic trong Docker và gửi `POST /ask?question=What%20is%20Docker%3F` nhận được HTTP `200` với response sau:

```json
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

## Part 3 — Cloud Deployment

- Agent Part 6 chạy trên Render Free tại [day14-agent.onrender.com](https://day14-agent.onrender.com). Xem kết quả kiểm tra và ảnh trong [DEPLOYMENT.md](DEPLOYMENT.md).
- Railway dùng TOML để chọn Dockerfile và đường dẫn health check, còn Redis được thêm vào project và gắn vào web service bằng tham chiếu biến. Render dùng Blueprint YAML có thể khai báo cùng lúc web service, Key Value nội bộ, secret sinh tự động và tham chiếu URL giữa hai service.
- Cloud Build cài dependencies và chạy pytest ở bước test. Bước build tạo tag theo commit và tag `latest`, sau đó push cả hai tag lên registry.
- Bước deploy chọn image theo commit để đưa lên Cloud Run, đặt giới hạn tài nguyên, số instance và nạp secret từ Secret Manager.
- `service.yaml` mô tả cấu hình chạy tương đương dưới dạng IaC, gồm cổng 8000, concurrency 80, min/max replica và probe `/health`, `/ready`.

## Part 4 — API Security

### 4.1–4.3. Kết quả curl

```text
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

HTTP/1.1 200 OK
{"question":"What is docker?","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

JWT (đã che token): request 1–10 → 200
Request 11:
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
Request 12: 429
```

JWT có chữ ký và thời hạn. Dịch vụ xác minh token trước khi áp rate limit theo người dùng. Bản demo trả `Retry-After` để client biết phải đợi bao lâu.

### 4.4. Cost guard

Trước khi gọi LLM, so số tiền đã dùng với ngân sách. Sau khi nhận kết quả, tính chi phí input và output theo giá riêng của mỗi loại token rồi cộng vào kỳ hiện tại. Part 6 lưu số tiền dưới dạng số nguyên nano-USD trong Redis và đặt TTL tới cuối kỳ UTC. Rate limit kiểm số request, cost guard xét mức tiêu thụ vì độ dài và giá mỗi lượt gọi có thể khác nhau. Một lượt gọi đã được chấp nhận có thể đưa chi tiêu vượt ngưỡng, vì chi phí được ghi sau khi sinh xong câu trả lời.

## Part 5 — Scaling & Reliability

- `GET /health` kiểm tra liveness. `GET /ready` theo dõi khả năng nhận tải. Ở Part 6, mất Redis làm `/ready` trả `503` trong khi `/health` vẫn trả `200`.
- Ở bản develop, gửi SIGTERM khi `POST /ask` đang chạy. Request hoàn tất với `200`, log ghi quá trình shutdown và tiến trình thoát mã `0`.
- Test qua Nginx với 3 replica. Cùng một session đi qua 3 instance và Redis giữ đủ 10 message sau 5 lượt hỏi. State trong RAM của từng worker sẽ làm các lượt sau thấy những phần lịch sử khác nhau.

```text
Total requests: 5
Instances used: {'instance-e17026', 'instance-82ef36', 'instance-eb9a46'}
✅ All requests served despite different instances!
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

## Part 6 — Output script chấm

```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 44/44 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

## AI log

- Yêu cầu AI đọc repo, tóm tắt và triển khai toàn bộ lab. AI hỗ trợ viết agent, cấu hình Docker/cloud, sửa hai mục knowledge base và thu kết quả từ các lệnh chạy trong workspace.
- AI kiểm tra bằng script chấm đầy đủ với Docker, chạy curl, test stateless, eval và load test, rồi triển khai lên Render sau khi người dùng cấp phiên đăng nhập. Các kết quả trong báo cáo lấy từ lần chạy này.
- Yêu cầu AI rà toàn bộ tài liệu Markdown và bổ sung bằng chứng còn thiếu. AI đối chiếu JSON/CSV với báo cáo, chạy lại ví dụ Docker basic và thử quality gate khi hạ từ v2 xuống v1.

### Tự kiểm tra

- Tôi mở Render Dashboard, xác nhận service `day14-agent` ở trạng thái **Deploy succeeded | Live** và chụp lại màn hình. [Ảnh Render Dashboard](screenshots/dashboard.png)
- Tôi mở endpoint `GET /health` trên URL public và nhận `{"status":"ok"}`. [Kết quả health](https://day14-agent.onrender.com/health)
- Tôi mở endpoint `GET /ready` trên URL public và nhận `{"ready":true}`. [Kết quả readiness](https://day14-agent.onrender.com/ready)
