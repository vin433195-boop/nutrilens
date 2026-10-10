"""Các phép tính dinh dưỡng dùng chung: % nhu cầu ngày, tỉ lệ macro, điểm sức khỏe, quy đổi vận động."""

from __future__ import annotations

# Giá trị tham chiếu cho chế độ ăn 2.000 kcal/ngày.
# Natri, đường tự do và chất xơ theo khuyến nghị của WHO; các chất còn lại theo nhãn dinh dưỡng phổ biến.
DAILY_VALUES = {
    "calories": 2000,
    "carbohydrate": 275,
    "protein": 50,
    "lipid": 70,
    "fiber": 25,
    "sugar": 50,
    "sodium": 2000,
}

# Hệ số MET để quy đổi calo sang thời gian vận động (người 60 kg).
ACTIVITIES = [
    ("walk", "Đi bộ nhanh", "🚶", 3.5),
    ("bike", "Đạp xe", "🚴", 6.8),
    ("run", "Chạy bộ", "🏃", 9.8),
    ("swim", "Bơi lội", "🏊", 6.0),
]
REFERENCE_WEIGHT_KG = 60

CATEGORY_ORDER = ["Món chính", "Món nước", "Ăn nhẹ", "Món rau", "Salad", "Tráng miệng"]


def pretty(name: str) -> str:
    return name.replace("_", " ").title()


class NutritionMixin:
    """Cần các thuộc tính: calories, carbohydrate, protein, lipid, fiber, sugar, sodium, slug, category..."""

    @property
    def macro_kcal(self) -> dict[str, float]:
        return {
            "carbohydrate": self.carbohydrate * 4,
            "protein": self.protein * 4,
            "lipid": self.lipid * 9,
        }

    @property
    def macro_percent(self) -> dict[str, int]:
        kcal = self.macro_kcal
        total = sum(kcal.values()) or 1
        pct = {k: round(v * 100 / total) for k, v in kcal.items()}
        diff = 100 - sum(pct.values())  # Làm tròn sao cho tổng đúng 100
        if diff:
            biggest = max(pct, key=pct.get)
            pct[biggest] += diff
        return pct

    def daily_percent(self, nutrient: str) -> int:
        return round(getattr(self, nutrient) * 100 / DAILY_VALUES[nutrient])

    # Điểm sức khỏe 1–10 (heuristic đơn giản, chỉ để tham khảo)
    @property
    def health_score(self) -> float:
        score = 10.0
        pct = self.macro_percent
        if self.calories > 400:
            score -= 1.5
        elif self.calories > 300:
            score -= 0.75
        if pct["lipid"] > 45:
            score -= 2
        elif pct["lipid"] > 35:
            score -= 1
        if pct["protein"] < 10:
            score -= 1.5
        elif pct["protein"] < 15:
            score -= 0.75
        if self.sugar > 20:
            score -= 2
        elif self.sugar > 10:
            score -= 1
        if self.sodium > 1200:
            score -= 1.5
        elif self.sodium > 800:
            score -= 0.75
        if self.fiber >= 3:
            score += 0.5
        return round(max(1.0, min(10.0, score)), 1)

    @property
    def health_label(self) -> tuple[str, str]:
        s = self.health_score
        if s >= 7.5:
            return "Lành mạnh", "good"
        if s >= 5.5:
            return "Cân bằng", "ok"
        return "Nên hạn chế", "limit"

    @property
    def exercise(self) -> list[dict]:
        out = []
        for key, label, icon, met in ACTIVITIES:
            kcal_per_min = met * 3.5 * REFERENCE_WEIGHT_KG / 200
            out.append({"key": key, "label": label, "icon": icon,
                        "minutes": round(self.calories / kcal_per_min)})
        return out

    def to_dict(self) -> dict:
        label, level = self.health_label
        return {
            "slug": self.slug,
            "name_vi": self.name_vi,
            "name_en": self.name_en,
            "emoji": self.emoji,
            "category": self.category,
            "cuisine": self.cuisine,
            "serving": self.serving,
            "serving_grams": getattr(self, "serving_grams", None),
            "nutrition": {
                "calories": self.calories,
                "carbohydrate": self.carbohydrate,
                "protein": self.protein,
                "lipid": self.lipid,
                "fiber": self.fiber,
                "sugar": self.sugar,
                "sodium": self.sodium,
            },
            "macro_percent": self.macro_percent,
            "health_score": self.health_score,
            "health_label": label,
            "health_level": level,
            "tags": self.tags,
            "image": f"/static/{self.image_path}" if getattr(self, "image_path", None) else None,
            "url": f"/mon-an/{self.slug}",
        }
