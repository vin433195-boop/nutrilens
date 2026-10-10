# NutriLens: website ẩm thực và dinh dưỡng

Website Flask giúp người dùng nhận dạng món ăn bằng AI, tra cứu dinh dưỡng, tính nhu cầu calo và theo dõi nhật ký ăn uống. Dữ liệu lưu trên MySQL/MariaDB, có đăng ký và đăng nhập. Phát triển từ dự án nhận dạng món ăn bằng CNN (Project 7).

## Cài đặt lần đầu (XAMPP trên Windows)

1. Mở XAMPP Control Panel và bấm **Start** ở dòng MySQL.
2. Cài thư viện:
   ```bash
   pip install -r requirements.txt
   ```
3. Tạo file cấu hình: sao chép `.env.example` thành `.env`, điền `SECRET_KEY`. Mặc định kết nối `root` không mật khẩu của XAMPP.
4. Tạo database, bảng và nạp dữ liệu mẫu bằng một lệnh:
   ```bash
   flask --app app setup-db
   ```
5. Chạy website rồi mở http://127.0.0.1:5000:
   ```bash
   python app.py
   ```

Database `nutrilens` sẽ xuất hiện trong phpMyAdmin tại http://localhost/phpmyadmin.

## Lệnh quản trị

| Lệnh | Tác dụng |
|---|---|
| `flask --app app setup-db` | Tạo database nếu chưa có, chạy migration, nạp dữ liệu mẫu. Chạy lại nhiều lần vẫn an toàn |
| `flask --app app seed` | Nạp món ăn và bài viết mới từ file. Thêm `--overwrite` để ghi đè dữ liệu đã sửa trong CSDL |
| `flask --app app create-admin` | Tạo tài khoản quản trị |
| `flask --app app db migrate -m "mô tả"` | Sinh migration sau khi sửa `nutrilens/models.py` |
| `flask --app app db upgrade` | Áp dụng migration vào database |

## Cơ sở dữ liệu

| Bảng | Nội dung |
|---|---|
| `users` | Tài khoản: email, mật khẩu đã băm scrypt, vai trò, đếm lần đăng nhập sai |
| `profiles` | Chỉ số cơ thể và mục tiêu calo, macro của từng người |
| `categories`, `tags`, `food_tags` | Danh mục và thẻ món ăn |
| `foods`, `food_notes` | Món ăn, dinh dưỡng mỗi khẩu phần, điểm cộng và mẹo ăn lành mạnh |
| `model_labels` | Ánh xạ nhãn của model AI sang món ăn |
| `articles` | Bài viết, nội dung Markdown |
| `diary_entries` | Nhật ký ăn uống, lưu lại dinh dưỡng tại thời điểm ghi |
| `recognitions` | Lịch sử nhận dạng và món người dùng sửa lại. Ảnh không được lưu |
| `contact_messages`, `subscribers` | Tin nhắn liên hệ và đăng ký bản tin |

Các file trong `nutrilens/data/` cùng `Mapping_Calories.json` chỉ là **dữ liệu khởi tạo** cho lệnh `seed`. Khi website chạy, mọi dữ liệu được đọc từ MySQL. File `class_names.json` vẫn cần vì nó quy định thứ tự đầu ra của file model.

## Tài khoản người dùng

- **Đăng ký:** họ tên, email, mật khẩu ít nhất 8 ký tự gồm chữ và số, đồng ý chính sách quyền riêng tư.
- **Đăng nhập:** tùy chọn ghi nhớ 30 ngày. Tài khoản bị khóa 15 phút sau 5 lần nhập sai mật khẩu.
- **Quên mật khẩu:** gửi link có hiệu lực 60 phút. Link tự hết hiệu lực khi mật khẩu đã đổi. Khi chưa cấu hình email, link được in ra cửa sổ dòng lệnh đang chạy website.
- **Trang tài khoản:** đổi tên, đổi mật khẩu, xem thống kê, xóa tài khoản kèm toàn bộ dữ liệu.
- **Đồng bộ:** khách vẫn dùng được nhật ký, dữ liệu lưu trên trình duyệt. Sau khi đăng nhập, dữ liệu đó tự chuyển vào tài khoản.

## Trang và API

| Trang | Đường dẫn |
|---|---|
| Trang chủ, thư viện, chi tiết món | `/`, `/mon-an`, `/mon-an/<slug>` |
| Nhận dạng AI, công cụ tính, nhật ký, so sánh | `/nhan-dang`, `/cong-cu`, `/nhat-ky`, `/so-sanh` |
| Kiến thức, giới thiệu, liên hệ, quyền riêng tư | `/kien-thuc`, `/gioi-thieu`, `/lien-he`, `/chinh-sach-quyen-rieng-tu` |
| Tài khoản | `/dang-ky`, `/dang-nhap`, `/quen-mat-khau`, `/tai-khoan` |

API JSON, các request ghi dữ liệu cần header `X-CSRF-Token`:

- `GET /api/foods`, `GET /api/foods/<slug>`, `GET /api/status`
- `POST /api/predict`: gửi `image`, tùy chọn `tta=1`
- Cần đăng nhập: `GET|POST|DELETE /api/diary`, `PATCH|DELETE /api/diary/<id>`, `GET /api/diary/summary`, `POST /api/diary/import`, `GET|PUT /api/profile`, `GET|DELETE /api/recognitions`, `PATCH|DELETE /api/recognitions/<id>`

## Biến môi trường (file `.env`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `DATABASE_URL` | MySQL XAMPP, database `nutrilens` | Chuỗi kết nối SQLAlchemy |
| `SECRET_KEY` | tự tạo trong `instance/secret_key` | Khóa ký phiên đăng nhập, nên đặt cố định |
| `COOKIE_SECURE` | `0` | Đặt `1` khi chạy HTTPS |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_SENDER` | trống | SMTP để gửi email quên mật khẩu |
| `PRELOAD_MODEL` | `1` | Nạp model AI ở nền khi khởi động |
| `MODEL_PATH` | `food_model.h5` | Đường dẫn file model |

## Kiểm thử

```bash
python -m unittest discover -s tests -v
```

Bộ test dùng SQLite trong bộ nhớ và model giả, không cần bật MySQL hay TensorFlow.

## Cấu trúc

```
app.py                  Điểm khởi chạy
.env.example            Mẫu cấu hình
migrations/             Migration Alembic cho cấu trúc bảng
nutrilens/
  __init__.py           App factory, xử lý lỗi
  config.py             Cấu hình, đọc .env
  extensions.py         SQLAlchemy, Migrate, LoginManager
  models.py             Các bảng dữ liệu
  catalog.py            Truy vấn món ăn và bài viết
  nutrition.py          Tính % nhu cầu ngày, điểm sức khỏe, quy đổi vận động
  auth.py               Đăng ký, đăng nhập, quên mật khẩu, tài khoản
  api.py                API JSON
  views.py              Các trang
  seed.py, cli.py       Nạp dữ liệu và lệnh quản trị
  mail.py, security.py  Gửi email, CSRF, header bảo mật
  predictor.py          Model AI
  data/                 Dữ liệu khởi tạo
  templates/, static/   Giao diện
tests/                  Unit test
legacy/                 Bản Streamlit cũ
```

## Về mô hình

CNN 3 tầng Conv2D, L2 Regularization và Dropout (TensorFlow/Keras), huấn luyện trên 20 lớp của Food-101. Độ chính xác khoảng 40% trên 5.000 ảnh kiểm thử. Giao diện luôn hiển thị top-3 và cho phép người dùng chọn lại món đúng. Các lần chọn lại được lưu trong bảng `recognitions` để làm dữ liệu huấn luyện về sau.

Số liệu chất xơ, đường và natri là ước tính tham khảo. Thông tin trên website không thay thế tư vấn y tế.
