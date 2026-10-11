"""Chuyển food_model.h5 sang food_model.tflite để chạy AI trên máy chủ ít RAM (Render free 512 MB).

Cần TensorFlow đầy đủ (requirements-ml.txt). Chạy: python scripts/convert_tflite.py
Sau khi chuyển, script so sánh dự đoán của hai model trên ảnh món ăn trong static/img/foods.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nutrilens.predictor import Predictor  # noqa: E402


def main() -> int:
    src = ROOT / "food_model.h5"
    dst = ROOT / "food_model.tflite"
    import tensorflow as tf

    keras_model = Predictor(src, []).load()
    converter = tf.lite.TFLiteConverter.from_keras_model(keras_model)
    dst.write_bytes(converter.convert())
    print(f"Đã tạo {dst.name}: {dst.stat().st_size / 1e6:.1f} MB (h5: {src.stat().st_size / 1e6:.1f} MB)")

    # So sánh xác suất của hai model trên ảnh thật
    lite = Predictor(dst, [])
    lite.load()
    size = lite.img_size
    images = sorted((ROOT / "nutrilens" / "static" / "img" / "foods").glob("*.webp"))
    if not images:
        print("Không tìm thấy ảnh để so sánh.")
        return 0
    batch = np.stack([np.asarray(Image.open(p).convert("RGB").resize(size), dtype=np.float32) / 255.0
                      for p in images])
    a = np.asarray(keras_model.predict(batch, verbose=0))
    b = np.asarray(lite._model.predict(batch))
    same = int((a.argmax(1) == b.argmax(1)).sum())
    print(f"{len(images)} ảnh: cùng nhãn top-1 {same}/{len(images)}, "
          f"chênh lệch xác suất lớn nhất {np.abs(a - b).max():.2e}")
    return 0 if same == len(images) else 1


if __name__ == "__main__":
    raise SystemExit(main())
