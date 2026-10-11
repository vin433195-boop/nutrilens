"""Bộ nhận dạng món ăn bằng CNN (food_model.tflite hoặc food_model.h5).

TensorFlow nặng và khởi động chậm, nên model chỉ được nạp ở lần nhận dạng đầu tiên
(hoặc ngay khi khởi động nếu PRELOAD_MODEL=1). Website vẫn chạy bình thường khi
không có TensorFlow hoặc không có file model; chỉ tính năng nhận dạng bị tắt.

File .tflite chạy bằng LiteRT (ai-edge-litert, ~100 MB RAM) thay cho TensorFlow
đầy đủ (~1 GB), phù hợp máy chủ miễn phí. Tạo bằng scripts/convert_tflite.py.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

log = logging.getLogger(__name__)


class PredictorUnavailable(RuntimeError):
    pass


def _tflite_interpreter_class():
    try:
        from ai_edge_litert.interpreter import Interpreter
    except ImportError:
        try:
            from tflite_runtime.interpreter import Interpreter
        except ImportError:
            import tensorflow as tf
            Interpreter = tf.lite.Interpreter
    return Interpreter


class _TFLiteModel:
    """Bọc Interpreter để có cùng giao diện input_shape/predict như model Keras."""

    def __init__(self, path: Path):
        self._interp = _tflite_interpreter_class()(model_path=str(path))
        self._interp.allocate_tensors()
        self._in = self._interp.get_input_details()[0]["index"]
        self._out = self._interp.get_output_details()[0]["index"]
        self.input_shape = tuple(int(d) for d in self._interp.get_input_details()[0]["shape"])
        self._batch = self.input_shape[0]
        self._lock = threading.Lock()  # Interpreter không an toàn khi nhiều luồng gọi cùng lúc

    def predict(self, batch: np.ndarray, verbose: int = 0) -> np.ndarray:
        batch = np.ascontiguousarray(batch, dtype=np.float32)
        with self._lock:
            if batch.shape[0] != self._batch:
                self._interp.resize_tensor_input(self._in, list(batch.shape))
                self._interp.allocate_tensors()
                self._batch = batch.shape[0]
            self._interp.set_tensor(self._in, batch)
            self._interp.invoke()
            return self._interp.get_tensor(self._out).copy()


class Predictor:
    def __init__(self, model_path: Path, class_names: list[str], model=None):
        self.model_path = Path(model_path)
        self.class_names = class_names
        self._model = model
        self._error: str | None = None
        self._lock = threading.Lock()
        self.img_size = (128, 128)
        if model is not None:
            self._read_input_size()

    # ── Trạng thái ─────────────────────────────────────────
    @property
    def status(self) -> str:
        if self._model is not None:
            return "ready"
        if self._error:
            return "error"
        if not self.model_path.exists():
            return "missing"
        return "idle"

    @property
    def error(self) -> str | None:
        return self._error

    # ── Nạp model ──────────────────────────────────────────
    def _read_input_size(self):
        shape = getattr(self._model, "input_shape", None)
        if shape and len(shape) >= 3 and shape[1] and shape[2]:
            self.img_size = (int(shape[1]), int(shape[2]))

    def load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if not self.model_path.exists():
                raise PredictorUnavailable(f"Không tìm thấy file model: {self.model_path.name}")
            try:
                log.info("Loading model %s ...", self.model_path)
                if self.model_path.suffix == ".tflite":
                    self._model = _TFLiteModel(self.model_path)
                else:
                    self._model = self._load_keras()
                self._read_input_size()
                self._error = None
                log.info("Model ready, input size %s", self.img_size)
            except Exception as exc:  # noqa: BLE001 - báo lỗi rõ ràng cho giao diện
                self._error = f"{type(exc).__name__}: {exc}"
                log.exception("Failed to load model")
                raise PredictorUnavailable("Không nạp được model nhận dạng.") from exc
        return self._model

    def _load_keras(self):
        import tensorflow as tf
        from tensorflow.keras.layers import Dense as _BaseDense

        class _CompatDense(_BaseDense):
            # Model được lưu bằng Keras mới hơn có thêm khóa quantization_config
            @classmethod
            def from_config(cls, config):
                config.pop("quantization_config", None)
                return super().from_config(config)

        return tf.keras.models.load_model(
            self.model_path, custom_objects={"Dense": _CompatDense}, compile=False)

    # ── Dự đoán ────────────────────────────────────────────
    def _to_array(self, img: Image.Image) -> np.ndarray:
        return np.asarray(img.convert("RGB").resize(self.img_size), dtype=np.float32) / 255.0

    @staticmethod
    def _variants(img: Image.Image) -> list[Image.Image]:
        """Test-Time Augmentation: 5 biến thể của cùng một ảnh."""
        w, h = img.size
        mw, mh = int(w * 0.1), int(h * 0.1)
        return [
            img,
            img.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
            ImageEnhance.Brightness(img).enhance(1.3),
            ImageEnhance.Brightness(img).enhance(0.7),
            img.crop((mw, mh, w - mw, h - mh)).resize((w, h), Image.Resampling.LANCZOS),
        ]

    def predict(self, img: Image.Image, tta: bool = False, top_k: int = 3) -> list[tuple[str, float]]:
        model = self.load()
        img = ImageOps.exif_transpose(img).convert("RGB")
        images = self._variants(img) if tta else [img]
        batch = np.stack([self._to_array(v) for v in images])
        proba = np.asarray(model.predict(batch, verbose=0)).mean(axis=0)
        order = np.argsort(proba)[::-1][:top_k]
        return [(self.class_names[i], float(proba[i])) for i in order]
