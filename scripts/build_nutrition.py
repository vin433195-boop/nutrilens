"""Tính dinh dưỡng cho từng món từ dữ liệu USDA FoodData Central.

Đầu vào:  nutrilens/data/nutrition_spec.json (công thức: mã fdcId + số gram của từng thành phần)
Đầu ra:   nutrilens/data/nutrition.json (giá trị cho 1 khẩu phần, cho 100 g, danh sách thành phần, nguồn)

Dữ liệu USDA (tải miễn phí tại https://fdc.nal.usda.gov/download-datasets):
  - FNDDS 2021-2023: FoodData_Central_survey_food_csv_2024-10-31.zip
  - SR Legacy:       FoodData_Central_sr_legacy_food_csv_2018-04.zip
Giải nén cả hai vào cùng một thư mục rồi chạy:
  python scripts/build_nutrition.py <thư mục chứa dữ liệu USDA>
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "nutrilens" / "data" / "nutrition_spec.json"
OUT = ROOT / "nutrilens" / "data" / "nutrition.json"

# FNDDS dùng mã số chất dinh dưỡng (208, 203...), SR Legacy dùng mã id (1008, 1003...)
NUTRIENTS = {
    "calories": ("1008", "208"), "carbohydrate": ("1005", "205"), "protein": ("1003", "203"),
    "lipid": ("1004", "204"), "fiber": ("1079", "291"), "sugar": ("2000", "269"), "sodium": ("1093", "307"),
}
DATASETS = {"survey": "USDA FNDDS 2021–2023", "sr_legacy": "USDA SR Legacy (2018)"}


def find_dirs(base: Path) -> dict[str, Path]:
    found = {}
    for food_csv in base.rglob("food.csv"):
        name = food_csv.parent.name
        for key in DATASETS:
            if f"_{key}_food_csv" in name:
                found[key] = food_csv.parent
    missing = set(DATASETS) - set(found)
    if missing:
        sys.exit(f"Không tìm thấy dữ liệu USDA: {', '.join(missing)} trong {base}")
    return found


def load(base: Path, wanted: set[int]) -> dict[int, dict]:
    lookup = {code: name for name, codes in NUTRIENTS.items() for code in codes}
    foods: dict[int, dict] = {}
    for key, folder in find_dirs(base).items():
        with open(folder / "food.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                fid = int(r["fdc_id"])
                if fid in wanted:
                    foods[fid] = {"description": r["description"], "dataset": DATASETS[key], "per100": {}}
        with open(folder / "food_nutrient.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                fid = int(r["fdc_id"])
                name = lookup.get(r["nutrient_id"])
                if fid in foods and name and r["amount"]:
                    foods[fid]["per100"][name] = float(r["amount"])
    return foods


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    spec = {k: v for k, v in json.loads(SPEC.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    wanted = {item[0] for dish in spec.values() for item in dish["items"] if item[0]}
    foods = load(Path(sys.argv[1]), wanted)
    missing = wanted - set(foods)
    if missing:
        sys.exit(f"Thiếu mã fdcId trong dữ liệu USDA: {sorted(missing)}")

    out = {}
    for slug, dish in spec.items():
        totals = dict.fromkeys(NUTRIENTS, 0.0)
        grams = 0.0
        ingredients, datasets = [], []
        for fdc_id, g, label in dish["items"]:
            grams += g
            if fdc_id is None:
                ingredients.append({"name": label, "grams": g, "fdc_id": None, "usda": "Nước (0 kcal)"})
                continue
            food = foods[fdc_id]
            for k in NUTRIENTS:
                totals[k] += food["per100"].get(k, 0.0) * g / 100
            ingredients.append({"name": label, "grams": g, "fdc_id": fdc_id, "usda": food["description"]})
            if food["dataset"] not in datasets:
                datasets.append(food["dataset"])
        per_serving = {k: round(v, 1) if k != "sodium" else round(v) for k, v in totals.items()}
        per_serving["calories"] = round(totals["calories"])
        method = "trực tiếp từ" if len(dish["items"]) == 1 else "tính theo công thức từ"
        out[slug] = {
            "serving": dish["serving"],
            "serving_grams": round(grams),
            "nutrition": per_serving,
            "per100": {k: round(v * 100 / grams, 1) for k, v in totals.items()},
            "ingredients": ingredients,
            "source": f"Số liệu {method} {', '.join(datasets)}",
        }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Đã ghi {len(out)} món vào {OUT.relative_to(ROOT)}")
    for slug, d in out.items():
        n = d["nutrition"]
        print(f"  {slug:22} {d['serving_grams']:>4} g  {n['calories']:>4} kcal  P {n['protein']:>5}  C {n['carbohydrate']:>5}  F {n['lipid']:>5}  Na {n['sodium']:>5}")


if __name__ == "__main__":
    main()
