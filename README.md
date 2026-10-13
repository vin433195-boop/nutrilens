# NutriLens: website ẩm thực và dinh dưỡng

Website Flask giúp người dùng tra cứu dinh dưỡng của 54 món ăn (36 món Việt Nam, 18 món quốc tế), nhận dạng 30 món Việt bằng AI, tính nhu cầu calo, ghi nhật ký ăn uống và theo dõi cân nặng. Dữ liệu lưu trên MySQL/MariaDB, số liệu dinh dưỡng lấy từ USDA FoodData Central, ảnh món ăn từ Wikimedia Commons.

## Cài đặt trên máy (Windows + XAMPP)

1. Mở XAMPP Control Panel, bấm **Start** ở dòng MySQL.
2. Cài thư viện:
   ```bash
   pip install -r requirements-ml.txt     # có AI nhận dạng (TensorFlow, ~500 MB)
   pip install -r requirements.txt        # hoặc chỉ website, không có AI
   ```
3. Sao chép `.env.example` thành `.env`, điền `SECRET_KEY` và `DATABASE_URL`.
4. Tạo database, bảng và dữ liệu mẫu:
   ```bash
   flask --app app setup-db
   flask --app app create-admin          # tạo hoặc nâng quyền tài khoản quản trị
   ```
5. Chạy website rồi mở http://127.0.0.1:5000:
   ```bash
   python app.py
   ```

## Tính năng

| Nhóm | Nội dung |
|---|---|
| Thư viện món ăn | 54 món, ảnh thật, tìm kiếm không dấu, lọc danh mục, sắp xếp, phân trang, món yêu thích |
| Trang món ăn | Nhãn dinh dưỡng, tỉ lệ macro, điểm sức khỏe, bảng thành phần kèm link tra cứu USDA, dữ liệu schema.org |
| Nhận dạng AI | 30 món Việt (EfficientNetV2-B0, 87,6% top-1, 96,3% top-3), chế độ TTA, người dùng chọn lại món đúng để làm dữ liệu huấn luyện |
| Nhật ký | Ghi theo khẩu phần hoặc gram, món tự thêm, mục tiêu cá nhân, đồng bộ từ trình duyệt khi đăng nhập |
| Báo cáo | Calo 7/30/90 ngày, macro trung bình, món ăn nhiều nhất, biểu đồ cân nặng |
| Tài khoản | Đăng ký, xác thực email, quên mật khẩu, đăng xuất mọi thiết bị, tải dữ liệu JSON/CSV, xóa tài khoản |
| Quản trị `/quan-tri` | Món ăn (kèm tải ảnh), bài viết, tin nhắn, người dùng, thống kê độ chính xác AI, xuất CSV |

## Bảo mật

- Mật khẩu băm scrypt, phiên dùng cookie HttpOnly, chống CSRF trên mọi form và API ghi dữ liệu.
- Giới hạn request theo IP cho đăng nhập, đăng ký, quên mật khẩu, nhận dạng, liên hệ.
- Đăng nhập sai bị giới hạn theo cặp IP và email, không khóa tài khoản nên không thể lợi dụng để khóa người khác.
- Đổi hoặc đặt lại mật khẩu sẽ đăng xuất mọi thiết bị khác.
- Header Content-Security-Policy dùng nonce, X-Frame-Options, Permissions-Policy, HSTS khi chạy HTTPS.
- Dùng tài khoản MySQL riêng chỉ có quyền trên database `nutrilens`.

## Số liệu dinh dưỡng

`scripts/build_nutrition.py` đọc công thức trong `nutrilens/data/nutrition_spec.json` và dữ liệu USDA (FNDDS 2021–2023, SR Legacy) để tạo `nutrilens/data/nutrition.json`. Website và lệnh seed chỉ đọc file kết quả, không cần dữ liệu USDA khi chạy. Cách tính được giải thích tại trang `/phuong-phap`.

Thêm hoặc sửa món qua trang quản trị, hoặc sửa file dữ liệu rồi chạy `flask --app app seed`. Thêm `--overwrite` để ghi đè dữ liệu đã có.

## Email

Web gửi mail qua **Brevo** (API HTTPS, gói miễn phí) khi có `BREVO_API_KEY`, hoặc qua SMTP khi có `MAIL_SERVER`. Không cấu hình gì thì link xác thực và đặt lại mật khẩu được in ra cửa sổ dòng lệnh. Trên Render bản miễn phí phải dùng Brevo vì cổng SMTP bị chặn. Cách lấy key xem trong `.env.example`.

Khi đăng ký, email được kiểm tra định dạng, lỗi gõ tên miền phổ biến (`gmial.com`), email dùng một lần và tên miền có máy chủ nhận thư (bản ghi MX). Khi đã cấu hình gửi mail, tài khoản mới phải bấm link trong email mới đăng nhập được (`REQUIRE_EMAIL_VERIFICATION`). Kiểm tra cấu hình:

```bash
flask --app app send-test-email ban@gmail.com
```

## Vận hành

| Việc | Cách làm |
|---|---|
| Chạy production | `waitress-serve --port=8000 --threads=4 app:app` |
| Kiểm tra sức khỏe | `GET /healthz` trả về trạng thái CSDL và model |
| Log | `logs/nutrilens.log`, tự xoay vòng 5 file × 5 MB |
| Theo dõi lỗi | Cài `sentry-sdk[flask]` và đặt `SENTRY_DSN` |
| Sao lưu | `flask --app app backup-db`, lưu `.sql.gz` vào `backups/`, giữ 14 bản |
| Sao lưu tự động trên Windows | Xem lệnh `schtasks` trong `deploy/backup_windows.bat` |

### Docker và HTTPS

```bash
# Điền DB_PASSWORD, DB_ROOT_PASSWORD, SECRET_KEY trong .env
docker compose up -d --build
# Có tên miền thật: Caddy tự cấp chứng chỉ HTTPS
DOMAIN=nutrilens.vn COOKIE_SECURE=1 docker compose --profile https up -d
```

Image mặc định chạy AI bằng LiteRT với `food_model.tflite` (khoảng 150 MB RAM). Dùng TensorFlow đầy đủ: `docker compose build --build-arg ML=full`; không có AI: `--build-arg ML=none`. Model được huấn luyện bằng notebook `training/train_vietnamese_food.ipynb` trên Google Colab (GPU T4); notebook xuất thẳng `food_model.tflite` và `class_names.json` để chép vào thư mục gốc, kết quả đánh giá ở `training/metrics.json`. Thêm món vào danh sách nhận dạng thì cũng cần thêm món đó vào `nutrilens/data/` rồi chạy `flask --app app seed`. Model chỉ biết 30 món Việt nên ảnh món nước ngoài vẫn bị gán vào món Việt gần giống nhất (ví dụ hamburger thành bánh mì).

### Đưa lên Render (miễn phí)

1. Tạo database MySQL trên mạng, ví dụ TiDB Cloud Serverless, rồi chạy `flask --app app setup-db` và `create-admin` từ máy với `DATABASE_URL` trỏ tới đó.
2. Đẩy code lên GitHub. Trên https://dashboard.render.com chọn **New → Blueprint**, chọn repo. Render đọc `render.yaml` và tạo dịch vụ.
3. Điền `DATABASE_URL` khi được hỏi. Với TiDB dùng `ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_cert=true&ssl_verify_identity=true`.
4. Muốn gửi email xác thực thật: trong **Environment** thêm `BREVO_API_KEY` và `MAIL_SENDER` (email người gửi đã xác minh trên Brevo).

Bản đang chạy: https://nutrilens-juer.onrender.com

Gói miễn phí tự ngủ sau 15 phút không có truy cập; lần mở lại chờ khoảng 1 phút. Ảnh tải lên qua trang quản trị mất khi dịch vụ khởi động lại.

## Kiểm thử

```bash
pip install -r requirements-dev.txt
ruff check .
python -m unittest discover -s tests -v
```

Test dùng SQLite trong bộ nhớ và model giả nên không cần MySQL hay TensorFlow. GitHub Actions tự chạy Ruff và test mỗi lần push, xem `.github/workflows/ci.yml`.

## Lệnh quản trị

| Lệnh | Tác dụng |
|---|---|
| `flask --app app setup-db` | Tạo database, chạy migration, nạp dữ liệu mẫu |
| `flask --app app seed [--overwrite]` | Nạp món ăn, ảnh, bài viết từ file |
| `flask --app app create-admin` | Tạo tài khoản quản trị |
| `flask --app app send-test-email <email>` | Gửi email thử để kiểm tra cấu hình Brevo hoặc SMTP |
| `flask --app app backup-db` | Sao lưu MySQL |
| `flask --app app db migrate -m "..."` / `db upgrade` | Tạo và áp dụng migration |

## Cấu trúc

```
app.py                    Điểm khởi chạy
nutrilens/
  __init__.py, config.py  App factory, cấu hình đọc từ .env
  models.py               Các bảng dữ liệu
  auth.py, admin.py       Tài khoản, trang quản trị
  api.py, views.py        API JSON, các trang
  catalog.py, nutrition.py  Truy vấn món ăn, tính toán dinh dưỡng
  seed.py, cli.py         Nạp dữ liệu, lệnh quản trị
  ops.py, security.py     Healthcheck, log, sao lưu, CSRF, header bảo mật
  mail.py, images.py      Email, xử lý ảnh tải lên
  predictor.py            Model AI
  data/                   foods.json, nutrition.json, images.json, bài viết
  static/, templates/     Giao diện
migrations/               Migration Alembic
scripts/                  Dựng số liệu dinh dưỡng từ USDA
deploy/                   Caddyfile, script sao lưu Windows
tests/                    Unit test
```

## Giấy phép dữ liệu

- Số liệu dinh dưỡng: USDA FoodData Central, thuộc phạm vi công cộng.
- Ảnh món ăn: Wikimedia Commons, giấy phép CC0, CC BY hoặc CC BY-SA. Tác giả và giấy phép từng ảnh nằm trong `nutrilens/data/images.json` và hiển thị dưới ảnh trên trang món ăn.
