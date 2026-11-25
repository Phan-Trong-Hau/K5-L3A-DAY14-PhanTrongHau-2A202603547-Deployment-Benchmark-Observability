# Deployment — Day 14

- **Nền tảng:** Render Free, Singapore
- **URL public:** [day14-agent.onrender.com](https://day14-agent.onrender.com)
- **Quản lý:** [Render Dashboard](https://dashboard.render.com/web/srv-dc397b3rjlhs73f78hs0)
- **Nguồn:** nhánh `day14-render`, commit `0d92dc14263286601ad2b484547d2b04025e36b7`

Render build Dockerfile từ thư mục gốc của service là `06-lab-complete/`. Web service kết nối với `day14-redis` qua mạng nội bộ cùng region. Cấu hình tương đương trong [Blueprint](06-lab-complete/render.yaml) đã được Render CLI xác thực. Bản đang chạy được tạo qua API Render.

Biến môi trường đã đặt trên web service gồm `PORT`, `ENVIRONMENT`, `AGENT_API_KEY` và `REDIS_URL`. Hai biến cuối được lưu trên Render. Key Value miễn phí lưu dữ liệu trong bộ nhớ, nên counter mất khi datastore bị khởi động lại.

## Kết quả kiểm tra public

| Yêu cầu | HTTP thực tế |
|---|---:|
| `GET /health` | 200 |
| `GET /ready` | 200 |
| `POST /ask`, thiếu API key | 401 |
| `POST /ask`, có API key hợp lệ | 200 |

Nạp `AGENT_API_KEY` từ Render vào môi trường shell trước khi chạy lệnh có xác thực.

```bash
BASE=https://day14-agent.onrender.com
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
```

## Ảnh

- [Trạng thái deploy](screenshots/dashboard.png), ảnh từ output Render CLI. Dashboard web cần phiên đăng nhập riêng.
- [Endpoint public đang chạy](screenshots/running.png), ảnh trực tiếp từ trình duyệt.
- [Kết quả kiểm tra HTTP](screenshots/test.png), ảnh từ output kiểm tra endpoint public.
