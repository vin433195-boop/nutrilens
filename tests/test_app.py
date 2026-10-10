"""Kiểm thử NutriLens. Chạy: python -m unittest discover -s tests -v

Test dùng SQLite trong bộ nhớ và model AI giả nên không cần MySQL hay TensorFlow.
"""

import io
import re
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy import func, select

from nutrilens import create_app
from nutrilens.auth import make_reset_token
from nutrilens.config import TestConfig
from nutrilens.extensions import db
from nutrilens.models import Article, ContactMessage, DiaryEntry, Food, Profile, Recognition, User
from nutrilens.predictor import Predictor
from nutrilens.seed import seed_all

PASSWORD = "matkhau123"


class FakeModel:
    """Model giả: luôn dự đoán lớp 'pho' cao nhất, không cần TensorFlow."""
    input_shape = (None, 64, 64, 3)

    def __init__(self, class_names):
        self.class_names = class_names
        self.calls = []

    def predict(self, batch, verbose=0):
        self.calls.append(batch.shape)
        n = len(self.class_names)
        proba = np.full((batch.shape[0], n), 0.1 / (n - 2))
        proba[:, self.class_names.index("pho")] = 0.85
        proba[:, self.class_names.index("ramen")] = 0.05
        return proba


def make_image(fmt="JPEG"):
    buf = io.BytesIO()
    Image.new("RGB", (200, 150), (200, 120, 60)).save(buf, format=fmt)
    buf.seek(0)
    return buf


class AppTestCase(unittest.TestCase):
    def setUp(self):
        import json
        names = json.loads(Path(TestConfig.CLASSES_PATH).read_text(encoding="utf-8"))
        self.model = FakeModel(names)
        self.app = self.build_app(TestConfig, names)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        seed_all()
        self.client = self.app.test_client()

    def build_app(self, config, names):
        app = create_app(config, predictor=Predictor(Path("missing.h5"), names, model=self.model))

        # Test giữ một app context suốt bài test nên mọi request dùng chung `g`.
        # Xóa người dùng đã cache để mỗi request tự xác thực lại như khi chạy thật.
        @app.before_request
        def _fresh_request_state():
            from flask import g
            g.pop("_login_user", None)
            g.pop("csp_nonce", None)
        return app

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    # ── Tiện ích ──
    def csrf(self, path="/"):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def make_user(self, email="an@example.com", name="Nguyễn An", password=PASSWORD):
        user = User(email=email, name=name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    def login(self, email="an@example.com", password=PASSWORD, **extra):
        token = self.csrf("/dang-nhap")
        return self.client.post("/dang-nhap", data={"csrf_token": token, "email": email,
                                                   "password": password, **extra})

    def api(self, method, url, json=None):
        token = self.csrf()
        return self.client.open(url, method=method, json=json, headers={"X-CSRF-Token": token})


# ════════════════════════════════════════════════════════════
class PageTests(AppTestCase):
    def test_all_pages_render(self):
        pages = ["/", "/mon-an", "/mon-an/pho", "/so-sanh", "/so-sanh?a=steak&b=donuts", "/nhan-dang",
                 "/cong-cu", "/nhat-ky", "/kien-thuc", "/kien-thuc/hieu-dung-ve-calo", "/gioi-thieu",
                 "/lien-he", "/chinh-sach-quyen-rieng-tu", "/dang-nhap", "/dang-ky", "/quen-mat-khau",
                 "/sitemap.xml", "/robots.txt"]
        for path in pages:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_every_dish_has_a_detail_page(self):
        for food in self.app.extensions["catalog"].all():
            with self.subTest(food=food.slug):
                res = self.client.get(f"/mon-an/{food.slug}")
                self.assertEqual(res.status_code, 200)
                self.assertIn(food.name_vi, res.get_data(as_text=True))

    def test_every_article_renders(self):
        for article in self.app.extensions["articles"].all():
            with self.subTest(article=article.slug):
                self.assertEqual(self.client.get(f"/kien-thuc/{article.slug}").status_code, 200)

    def test_404_page(self):
        res = self.client.get("/mon-an/khong-ton-tai")
        self.assertEqual(res.status_code, 404)
        self.assertIn("Không tìm thấy món ăn", res.get_data(as_text=True))

    def test_unpublished_food_is_hidden(self):
        food = db.session.scalar(select(Food).where(Food.slug == "donuts"))
        food.is_published = False
        db.session.commit()
        self.assertEqual(self.client.get("/mon-an/donuts").status_code, 404)
        self.assertEqual(self.client.get("/api/foods").get_json()["count"], 19)

    def test_header_shows_login_for_guests_and_menu_for_users(self):
        self.assertIn("Đăng ký", self.client.get("/").get_data(as_text=True))
        self.make_user()
        self.login()
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("data-user-menu", html)
        self.assertIn('data-auth="1"', html)


class SeedTests(AppTestCase):
    def test_seed_loads_all_data(self):
        self.assertEqual(db.session.scalar(select(func.count(Food.id))), 20)
        self.assertEqual(len(self.app.extensions["articles"].all()), 6)

    def test_macros_come_from_mapping_file(self):
        pho = self.app.extensions["catalog"].get("pho")
        self.assertEqual((pho.calories, pho.carbohydrate, pho.protein, pho.lipid), (350, 45, 20, 8))
        self.assertEqual(pho.category, "Món nước")
        self.assertTrue(pho.tips and pho.highlights and pho.tags)

    def test_seed_is_idempotent_and_keeps_edits(self):
        pho = self.app.extensions["catalog"].get("pho")
        pho.calories = 999
        db.session.commit()
        result = seed_all()
        self.assertEqual(result["foods"], (0, 0))
        self.assertEqual(self.app.extensions["catalog"].get("pho").calories, 999)
        seed_all(overwrite=True)
        self.assertEqual(self.app.extensions["catalog"].get("pho").calories, 350)

    def test_model_label_mapping(self):
        self.assertEqual(self.app.extensions["catalog"].by_label("spring_rolls").name_vi, "Chả giò")

    def test_search_and_related(self):
        catalog = self.app.extensions["catalog"]
        self.assertEqual({f.slug for f in catalog.search("Nhật")}, {"ramen", "sushi"})
        related = catalog.related(catalog.get("pho"))
        self.assertEqual(len(related), 4)
        self.assertEqual(related[0].category, "Món nước")

    def test_nutrition_helpers(self):
        for food in self.app.extensions["catalog"].all():
            self.assertEqual(sum(food.macro_percent.values()), 100, food.slug)
            self.assertTrue(1 <= food.health_score <= 10, food.slug)


# ════════════════════════════════════════════════════════════
class RegisterTests(AppTestCase):
    def post_register(self, **overrides):
        data = {"name": "Trần Bình", "email": "binh@example.com", "password": PASSWORD,
                "confirm": PASSWORD, "agree": "1"}
        data.update(overrides)
        return self.client.post("/dang-ky", data={"csrf_token": self.csrf("/dang-ky"), **data})

    def test_register_creates_user_and_logs_in(self):
        res = self.post_register(email="Binh@Example.com")
        self.assertEqual(res.status_code, 302)
        user = db.session.scalar(select(User).where(User.email == "binh@example.com"))
        self.assertIsNotNone(user)
        self.assertNotEqual(user.password_hash, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertIn("data-user-menu", self.client.get("/").get_data(as_text=True))

    def test_register_validation(self):
        cases = {
            "email": {"email": "khong-hop-le"},
            "password": {"password": "ngan", "confirm": "ngan"},
            "confirm": {"confirm": "khac123456"},
            "agree": {"agree": ""},
            "name": {"name": "A"},
        }
        for field, override in cases.items():
            with self.subTest(field=field):
                res = self.post_register(**override)
                self.assertEqual(res.status_code, 422)
        self.assertEqual(db.session.scalar(select(func.count(User.id))), 0)

    def test_password_needs_letters_and_digits(self):
        self.assertEqual(self.post_register(password="chiconchu", confirm="chiconchu").status_code, 422)

    def test_duplicate_email_rejected(self):
        self.make_user(email="binh@example.com")
        res = self.post_register()
        self.assertEqual(res.status_code, 422)
        self.assertIn("đã được đăng ký", res.get_data(as_text=True))

    def test_open_redirect_blocked_after_register(self):
        res = self.post_register(next="//evil.example")
        self.assertNotIn("evil", res.headers["Location"])


class LoginTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()

    def test_login_success_and_next_redirect(self):
        res = self.login(next="/nhat-ky")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers["Location"].endswith("/nhat-ky"))
        self.assertIsNotNone(db.session.get(User, self.user.id).last_login_at)

    def test_wrong_password_generic_error(self):
        res = self.login(password="sai123456")
        self.assertEqual(res.status_code, 401)
        self.assertIn("Email hoặc mật khẩu không đúng", res.get_data(as_text=True))
        res = self.login(email="khongco@example.com")
        self.assertIn("Email hoặc mật khẩu không đúng", res.get_data(as_text=True))

    def test_wrong_passwords_do_not_lock_the_account(self):
        # Không khóa theo tài khoản: kẻ xấu không thể khóa tài khoản của người khác
        for _ in range(8):
            self.login(password="sai123456")
        self.assertEqual(self.login().status_code, 302)

    def test_old_sessions_revoked_after_password_change(self):
        self.login()
        other = self.app.test_client()  # Thiết bị thứ hai
        token = re.search(r'csrf-token" content="([^"]+)', other.get("/dang-nhap").get_data(as_text=True)).group(1)
        other.post("/dang-nhap", data={"csrf_token": token, "email": "an@example.com", "password": PASSWORD})
        self.assertEqual(other.get("/tai-khoan").status_code, 200)
        self.client.post("/tai-khoan", data={"csrf_token": self.csrf("/tai-khoan"), "action": "password",
                                             "current": PASSWORD, "password": "moi123456", "confirm": "moi123456"})
        self.assertEqual(self.client.get("/tai-khoan").status_code, 200)  # Thiết bị đang dùng vẫn đăng nhập
        self.assertEqual(other.get("/tai-khoan").status_code, 302)        # Thiết bị kia bị đăng xuất

    def test_inactive_user_cannot_login(self):
        self.user.active = False
        db.session.commit()
        self.assertIn("vô hiệu hóa", self.login().get_data(as_text=True))

    def test_logout(self):
        self.login()
        token = self.csrf()
        self.client.post("/dang-xuat", data={"csrf_token": token})
        self.assertEqual(self.client.get("/tai-khoan").status_code, 302)

    def test_logout_requires_post_with_csrf(self):
        self.login()
        self.assertEqual(self.client.post("/dang-xuat").status_code, 400)
        self.assertEqual(self.client.get("/dang-xuat").status_code, 405)

    def test_account_requires_login(self):
        res = self.client.get("/tai-khoan")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/dang-nhap", res.headers["Location"])


class SecurityTests(AppTestCase):
    def test_security_headers_and_nonce(self):
        res = self.client.get("/")
        csp = res.headers["Content-Security-Policy"]
        nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
        self.assertIn(f'nonce="{nonce}"', res.get_data(as_text=True))
        self.assertEqual(res.headers["X-Content-Type-Options"], "nosniff")

    def test_rate_limit_on_login(self):
        class LimitedConfig(TestConfig):
            RATELIMIT_ENABLED = True

        app = self.build_app(LimitedConfig, self.model.class_names)
        client = app.test_client()
        with app.app_context():
            db.create_all()
            self.make_user()
            html = client.get("/dang-nhap").get_data(as_text=True)
            token = re.search(r'csrf-token" content="([^"]+)', html).group(1)
            codes = [client.post("/dang-nhap", data={"csrf_token": token, "email": "an@example.com",
                                                    "password": "sai123456"}).status_code for _ in range(6)]
            db.drop_all()
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(codes[5], 429)


class PasswordResetTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()

    def test_forgot_password_same_message_for_unknown_email(self):
        for email in ("an@example.com", "khongco@example.com"):
            token = self.csrf("/quen-mat-khau")
            res = self.client.post("/quen-mat-khau", data={"csrf_token": token, "email": email},
                                   follow_redirects=True)
            self.assertIn("Nếu email đã đăng ký", res.get_data(as_text=True))

    def test_reset_password_with_token(self):
        token = make_reset_token(self.user)
        csrf = self.csrf(f"/dat-lai-mat-khau/{token}")
        res = self.client.post(f"/dat-lai-mat-khau/{token}",
                               data={"csrf_token": csrf, "password": "moi123456", "confirm": "moi123456"})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(db.session.get(User, self.user.id).check_password("moi123456"))
        # Link chỉ dùng được một lần vì mật khẩu đã đổi
        res = self.client.get(f"/dat-lai-mat-khau/{token}")
        self.assertEqual(res.status_code, 302)

    def test_invalid_token(self):
        res = self.client.get("/dat-lai-mat-khau/token-gia")
        self.assertIn("/quen-mat-khau", res.headers["Location"])


class AccountTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.login()

    def post_account(self, **data):
        return self.client.post("/tai-khoan", data={"csrf_token": self.csrf("/tai-khoan"), **data})

    def test_update_name(self):
        self.post_account(action="profile", name="An Nguyễn")
        self.assertEqual(db.session.get(User, self.user.id).name, "An Nguyễn")

    def test_change_password(self):
        res = self.post_account(action="password", current="sai", password="moi123456", confirm="moi123456")
        self.assertEqual(res.status_code, 422)
        self.post_account(action="password", current=PASSWORD, password="moi123456", confirm="moi123456")
        self.assertTrue(db.session.get(User, self.user.id).check_password("moi123456"))

    def test_delete_account_removes_all_data(self):
        self.api("POST", "/api/diary", {"slug": "pho", "meal": "lunch"})
        self.api("PUT", "/api/profile", {"target": {"calories": 1800, "protein": 90, "carb": 200, "fat": 60}})
        res = self.post_account(action="delete", current_delete=PASSWORD, confirm_text="khong")
        self.assertEqual(res.status_code, 422)
        self.post_account(action="delete", current_delete=PASSWORD, confirm_text="XOA")
        self.assertIsNone(db.session.get(User, self.user.id))
        self.assertEqual(db.session.scalar(select(func.count(DiaryEntry.id))), 0)
        self.assertEqual(db.session.scalar(select(func.count(Profile.user_id))), 0)


# ════════════════════════════════════════════════════════════
class DiaryApiTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.login()

    def test_requires_login(self):
        self.client.post("/dang-xuat", data={"csrf_token": self.csrf()})
        res = self.client.get("/api/diary")
        self.assertEqual(res.status_code, 401)
        self.assertIn("error", res.get_json())

    def test_add_update_delete_entry(self):
        today = date.today().isoformat()
        res = self.api("POST", "/api/diary", {"slug": "pho", "meal": "lunch", "servings": 1.5, "date": today})
        self.assertEqual(res.status_code, 201)
        entry = res.get_json()
        self.assertEqual((entry["kcal"], entry["servings"]), (350, 1.5))

        self.api("PATCH", f"/api/diary/{entry['id']}", {"servings": 2})
        day = self.client.get(f"/api/diary?date={today}").get_json()
        self.assertEqual(day["entries"][0]["servings"], 2)

        self.api("DELETE", f"/api/diary/{entry['id']}")
        self.assertEqual(self.client.get(f"/api/diary?date={today}").get_json()["entries"], [])

    def test_entry_keeps_nutrition_snapshot(self):
        self.api("POST", "/api/diary", {"slug": "pho", "meal": "lunch"})
        pho = self.app.extensions["catalog"].get("pho")
        pho.calories = 500
        db.session.commit()
        self.assertEqual(self.client.get("/api/diary").get_json()["entries"][0]["kcal"], 350)

    def test_validation(self):
        bad = [{"slug": "khongco", "meal": "lunch"}, {"slug": "pho", "meal": "brunch"},
               {"slug": "pho", "meal": "lunch", "servings": 100}, {"slug": "pho", "meal": "lunch", "date": "hom-nay"}]
        for body in bad:
            with self.subTest(body=body):
                self.assertEqual(self.api("POST", "/api/diary", body).status_code, 400)

    def test_cannot_touch_other_users_entries(self):
        other = self.make_user(email="khac@example.com")
        pho = self.app.extensions["catalog"].get("pho")
        entry = DiaryEntry.from_food(other, pho, date.today(), "lunch", 1)
        db.session.add(entry)
        db.session.commit()
        self.assertEqual(self.api("PATCH", f"/api/diary/{entry.id}", {"servings": 3}).status_code, 404)
        self.assertEqual(self.api("DELETE", f"/api/diary/{entry.id}").status_code, 404)
        self.assertEqual(self.client.get("/api/diary").get_json()["entries"], [])

    def test_week_summary(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.api("POST", "/api/diary", {"slug": "pho", "meal": "lunch", "servings": 2, "date": yesterday})
        self.api("POST", "/api/diary", {"slug": "sushi", "meal": "dinner"})
        days = self.client.get("/api/diary/summary").get_json()["days"]
        self.assertEqual(len(days), 7)
        self.assertEqual(days[-2], {"date": yesterday, "kcal": 700})
        self.assertEqual(days[-1]["kcal"], 200)

    def test_clear_day(self):
        self.api("POST", "/api/diary", {"slug": "pho", "meal": "lunch"})
        self.api("DELETE", f"/api/diary?date={date.today().isoformat()}")
        self.assertEqual(self.client.get("/api/diary").get_json()["entries"], [])

    def test_import_from_browser(self):
        today = date.today().isoformat()
        payload = {"entries": {today: [{"slug": "pho", "meal": "lunch", "qty": 1},
                                       {"slug": "khongco", "meal": "lunch", "qty": 1},
                                       {"slug": "sushi", "meal": "xx", "qty": 1}]},
                   "target": {"calories": 1800, "protein": 90, "carb": 200, "fat": 60}}
        res = self.api("POST", "/api/diary/import", payload).get_json()
        self.assertEqual(res, {"imported": 1, "target": True})
        self.assertEqual(self.client.get("/api/profile").get_json()["target"]["calories"], 1800)

    def test_profile_round_trip(self):
        self.assertEqual(self.client.get("/api/profile").get_json()["target"]["calories"], 2000)
        body = {"sex": "female", "age": "30", "height": "158", "weight": "52.5", "activity": "1.55", "goal": "-250"}
        res = self.api("PUT", "/api/profile", {"target": {"calories": 1700, "protein": 85, "carb": 190, "fat": 57},
                                               "body": body})
        self.assertEqual(res.status_code, 200)
        data = self.client.get("/api/profile").get_json()
        self.assertEqual(data["body"]["weight"], 52.5)
        self.assertEqual(data["body"]["goal"], -250)
        self.assertEqual(self.api("PUT", "/api/profile", {"target": {"calories": 100, "protein": 1,
                                                                     "carb": 1, "fat": 1}}).status_code, 400)

    def test_calculator_prefills_from_profile(self):
        self.api("PUT", "/api/profile", {"target": {"calories": 1700, "protein": 85, "carb": 190, "fat": 57},
                                         "body": {"weight": "52.5"}})
        self.assertIn('"weight": 52.5', self.client.get("/cong-cu").get_data(as_text=True))


# ════════════════════════════════════════════════════════════
class PredictApiTests(AppTestCase):
    def predict(self, **extra):
        token = self.csrf()
        return self.client.post("/api/predict", data={"image": (make_image(), "pho.jpg"), **extra},
                                headers={"X-CSRF-Token": token}, content_type="multipart/form-data")

    def test_predict_returns_top3_with_nutrition(self):
        res = self.predict()
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()
        self.assertEqual(len(data["predictions"]), 3)
        top = data["predictions"][0]
        self.assertEqual((top["label"], top["level"]), ("pho", "high"))
        self.assertEqual(top["food"]["nutrition"]["calories"], 350)
        self.assertEqual(self.model.calls[-1], (1, 64, 64, 3))
        self.assertIsNone(data["recognition_id"])  # Khách: không trả id

    def test_tta_batches_five_variants(self):
        res = self.predict(tta="1")
        self.assertTrue(res.get_json()["tta"])
        self.assertEqual(self.model.calls[-1][0], 5)

    def test_logged_in_prediction_is_saved_and_correctable(self):
        self.make_user()
        self.login()
        rec_id = self.predict().get_json()["recognition_id"]
        self.assertIsNotNone(rec_id)
        items = self.client.get("/api/recognitions").get_json()["items"]
        self.assertEqual(items[0]["slug"], "pho")
        res = self.api("PATCH", f"/api/recognitions/{rec_id}", {"slug": "ramen"})
        self.assertTrue(res.get_json()["corrected"])
        self.assertEqual(db.session.get(Recognition, rec_id).corrected_food.slug, "ramen")
        self.api("DELETE", "/api/recognitions")
        self.assertEqual(self.client.get("/api/recognitions").get_json()["items"], [])

    def test_rejects_non_image(self):
        token = self.csrf()
        res = self.client.post("/api/predict", data={"image": (io.BytesIO(b"not an image"), "x.jpg")},
                               headers={"X-CSRF-Token": token}, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 400)

    def test_requires_csrf(self):
        res = self.client.post("/api/predict", data={"image": (make_image(), "pho.jpg")},
                               content_type="multipart/form-data")
        self.assertEqual(res.status_code, 400)

    def test_without_model_returns_503(self):
        self.app.extensions["predictor"] = Predictor(Path("missing.h5"), ["pho"])
        self.assertEqual(self.predict().status_code, 503)


class FormTests(AppTestCase):
    def test_contact_validation(self):
        token = self.csrf("/lien-he")
        res = self.client.post("/lien-he", data={"csrf_token": token, "name": "A", "email": "bad",
                                                 "topic": "Khác", "body": "ngắn"})
        self.assertEqual(res.status_code, 422)
        self.assertIn("Địa chỉ email không hợp lệ", res.get_data(as_text=True))

    def test_contact_success_saves_message(self):
        token = self.csrf("/lien-he")
        res = self.client.post("/lien-he", data={"csrf_token": token, "name": "Nguyễn An",
                                                 "email": "an@example.com", "topic": "Khác",
                                                 "body": "Website rất hữu ích, cảm ơn nhóm!"},
                               follow_redirects=True)
        self.assertIn("Cảm ơn bạn", res.get_data(as_text=True))
        self.assertEqual(db.session.scalar(select(func.count(ContactMessage.id))), 1)

    def test_newsletter_duplicate(self):
        token = self.csrf()
        for _ in range(2):
            res = self.client.post("/dang-ky-ban-tin", data={"csrf_token": token, "email": "a@b.vn", "next": "/"},
                                   follow_redirects=True)
        self.assertIn("đã đăng ký bản tin rồi", res.get_data(as_text=True))

    def test_newsletter_rejects_open_redirect(self):
        token = self.csrf()
        res = self.client.post("/dang-ky-ban-tin", data={"csrf_token": token, "email": "c@d.vn",
                                                         "next": "//evil.example"})
        self.assertEqual(res.headers["Location"], "/")



# ════════════════════════════════════════════════════════════
class AdminTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.make_user(email="admin@example.com", name="Quản Trị")
        self.admin.role = "admin"
        db.session.commit()

    def login_admin(self):
        self.login(email="admin@example.com")

    def post(self, url, data=None, **kw):
        return self.client.post(url, data={"csrf_token": self.csrf("/"), **(data or {})}, **kw)

    def food_form(self, **override):
        data = {"name_vi": "Bún chả", "name_en": "Bun cha", "slug": "", "category": "Món chính", "new_category": "",
                "cuisine": "Việt Nam", "serving": "1 suất (~400 g)", "serving_grams": "400", "description": "Bún chả Hà Nội",
                "highlights": "Nhiều rau\nĐạm từ thịt", "tips": "Ăn nhiều rau sống", "tags": "Việt Nam, nướng",
                "calories": "450", "carbohydrate": "55", "protein": "22", "lipid": "15", "fiber": "3", "sugar": "8",
                "sodium": "900", "source": "Ước tính", "is_published": "1", "emoji": "🍜", "model_label": "",
                "image_credit": "", "image_license": "", "image_source": ""}
        data.update(override)
        return data

    def test_access_control(self):
        self.assertEqual(self.client.get("/quan-tri/").status_code, 302)  # Chưa đăng nhập
        self.make_user()
        self.login()
        self.assertEqual(self.client.get("/quan-tri/").status_code, 403)  # Thành viên thường
        self.assertEqual(self.client.get("/quan-tri/mon-an").status_code, 403)

    def test_all_admin_pages_render(self):
        self.login_admin()
        db.session.add(ContactMessage(name="A", email="a@b.vn", topic="Khác", body="Xin chào quản trị"))
        db.session.commit()
        pho = self.app.extensions["catalog"].get("pho")
        article = self.app.extensions["articles"].all()[0]
        for url in ["/quan-tri/", "/quan-tri/mon-an", "/quan-tri/mon-an?loc=chua-co-anh", "/quan-tri/mon-an/them",
                    f"/quan-tri/mon-an/{pho.id}", "/quan-tri/bai-viet", "/quan-tri/bai-viet/them",
                    f"/quan-tri/bai-viet/{article.id}", "/quan-tri/tin-nhan", "/quan-tri/nguoi-dung",
                    "/quan-tri/nhan-dang", "/quan-tri/nhan-dang/xuat-csv"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_create_food_with_image(self):
        self.login_admin()
        data = self.food_form()
        data["image"] = (make_image(), "bun.jpg")
        res = self.post("/quan-tri/mon-an/them", data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 302, res.get_data(as_text=True)[:500])
        food = self.app.extensions["catalog"].get("bun_cha")
        self.assertIsNotNone(food)
        self.assertEqual((food.calories, food.serving_grams, food.category), (450, 400, "Món chính"))
        self.assertEqual(food.highlights, ["Nhiều rau", "Đạm từ thịt"])
        self.assertEqual(set(food.tags), {"việt nam", "nướng"})
        self.assertTrue(food.image_path.startswith("uploads/foods/bun_cha-"))
        path = Path(self.app.static_folder) / food.image_path
        self.assertTrue(path.exists())
        self.assertEqual(Image.open(path).format, "WEBP")
        path.unlink()

    def test_food_validation(self):
        self.login_admin()
        res = self.post("/quan-tri/mon-an/them", self.food_form(name_vi="", calories="-5", slug="Có Dấu"))
        self.assertEqual(res.status_code, 422)
        res = self.post("/quan-tri/mon-an/them", self.food_form(slug="pho"))
        self.assertIn("Slug này đã được dùng", res.get_data(as_text=True))

    def test_edit_food_and_new_category(self):
        self.login_admin()
        pho = self.app.extensions["catalog"].get("pho")
        res = self.post(f"/quan-tri/mon-an/{pho.id}", self.food_form(slug="pho", name_vi="Phở bò tái",
                                                                     new_category="Đặc sản Hà Nội", model_label="pho"))
        self.assertEqual(res.status_code, 302)
        pho = self.app.extensions["catalog"].get("pho")
        self.assertEqual((pho.name_vi, pho.category), ("Phở bò tái", "Đặc sản Hà Nội"))
        self.assertEqual(self.app.extensions["catalog"].by_label("pho").id, pho.id)

    def test_cannot_delete_food_used_in_diary(self):
        self.login_admin()
        pho = self.app.extensions["catalog"].get("pho")
        db.session.add(DiaryEntry.from_food(self.admin, pho, date.today(), "lunch", 1))
        db.session.commit()
        self.post(f"/quan-tri/mon-an/{pho.id}/xoa")
        self.assertIsNotNone(db.session.get(Food, pho.id))
        donuts = self.app.extensions["catalog"].get("donuts")
        self.post(f"/quan-tri/mon-an/{donuts.id}/xoa")
        self.assertIsNone(db.session.get(Food, donuts.id))

    def test_article_crud(self):
        self.login_admin()
        res = self.post("/quan-tri/bai-viet/them", {"title": "Ăn sáng đủ chất", "slug": "", "excerpt": "Tóm tắt",
                                                    "category": "Thực hành", "emoji": "🥣", "read_time": "",
                                                    "published_at": "2026-10-01", "is_published": "1",
                                                    "body_md": "## Vì sao\n\nBữa sáng giúp bạn tỉnh táo cả ngày."})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.client.get("/kien-thuc/an-sang-du-chat").status_code, 200)
        article = db.session.scalar(select(Article).where(Article.slug == "an-sang-du-chat"))
        self.post(f"/quan-tri/bai-viet/{article.id}/xoa")
        self.assertEqual(self.client.get("/kien-thuc/an-sang-du-chat").status_code, 404)

    def test_message_marked_read(self):
        self.login_admin()
        msg = ContactMessage(name="A", email="a@b.vn", topic="Khác", body="Xin chào quản trị")
        db.session.add(msg)
        db.session.commit()
        self.assertIn(">1<", self.client.get("/quan-tri/").get_data(as_text=True).replace(" ", ""))
        self.client.get(f"/quan-tri/tin-nhan/{msg.id}")
        self.assertTrue(db.session.get(ContactMessage, msg.id).is_read)

    def test_deactivate_user_and_self_protection(self):
        self.login_admin()
        user = self.make_user()
        self.post(f"/quan-tri/nguoi-dung/{user.id}", {"action": "deactivate"})
        self.assertFalse(db.session.get(User, user.id).active)
        self.post(f"/quan-tri/nguoi-dung/{self.admin.id}", {"action": "demote"})
        self.assertEqual(db.session.get(User, self.admin.id).role, "admin")

    def test_corrections_csv(self):
        self.login_admin()
        pho, ramen = (self.app.extensions["catalog"].get(s) for s in ("pho", "ramen"))
        db.session.add(Recognition(user_id=self.admin.id, predicted_label="pho", confidence=0.6, food=pho,
                                   corrected_food_id=ramen.id))
        db.session.commit()
        csv_text = self.client.get("/quan-tri/nhan-dang/xuat-csv").get_data(as_text=True)
        self.assertIn("pho,0.6,ramen", csv_text)


if __name__ == "__main__":
    unittest.main()
