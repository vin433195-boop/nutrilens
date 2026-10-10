# ============================================================
#  PROJECT 7 - GIAO DIỆN NHẬN DẠNG MÓN ĂN
#  File: app.py  |  Chạy: streamlit run app.py
# ============================================================

import io
import os
import json
import base64
import numpy as np
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageEnhance, UnidentifiedImageError

import streamlit as st
import tensorflow as tf
import plotly.graph_objects as go

# ─────────────────────────────────────────────
# Cấu hình trang
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Food Recognition",
    page_icon="🍽️",
    layout="wide",
)

st.markdown("""
<style>
[data-testid="metric-container"] {
    background: #f7f8fa;
    border-radius: 10px;
    padding: 10px 14px;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# Hằng số
# ─────────────────────────────────────────────
MODEL_PATH   = Path("food_model.h5")
CLASSES_PATH = Path("class_names.json")
MAPPING_PATH = Path("Mapping_Calories.json")
HISTORY_PATH = Path("history.json")
# Khi deploy lên server, KHÔNG lưu lịch sử ra file chung (mọi người truy cập sẽ thấy ảnh của nhau).
# Chạy trên máy cá nhân muốn lưu lịch sử: đặt biến môi trường PERSIST_HISTORY=1
PERSIST_HISTORY = os.environ.get("PERSIST_HISTORY", "0") == "1"
IMG_SIZE     = (128, 128)

def pretty(name: str) -> str:
    return name.replace("_", " ").title()

# ─────────────────────────────────────────────
# Load model & metadata
# ─────────────────────────────────────────────
@st.cache_resource(show_spinner="⏳ Đang tải model AI...")
def load_model():
    if not MODEL_PATH.exists():
        return None

    from tensorflow.keras.layers import Dense as _BaseDense

    class _CompatDense(_BaseDense):
        @classmethod
        def from_config(cls, config):
            config.pop("quantization_config", None)
            return super().from_config(config)

    return tf.keras.models.load_model(
        MODEL_PATH,
        custom_objects={"Dense": _CompatDense},
        compile=False,
    )

@st.cache_data
def load_metadata():
    class_names = []
    mapping     = {}

    if CLASSES_PATH.exists():
        with open(CLASSES_PATH, encoding="utf-8") as f:
            class_names = json.load(f)
    else:
        class_names = [
            "apple_pie", "caesar_salad", "cheesecake", "chicken_curry", "cup_cakes",
            "donuts", "fried_rice", "hamburger", "hot_dog", "ice_cream",
            "omelette", "pizza", "pho", "ramen", "spaghetti_bolognese",
            "spring_rolls", "steak", "sushi", "tacos", "waffles"
        ]

    if MAPPING_PATH.exists():
        with open(MAPPING_PATH, encoding="utf-8") as f:
            mapping = json.load(f)

    return class_names, mapping

# ─────────────────────────────────────────────
# Helpers — nhận dạng
# ─────────────────────────────────────────────
def preprocess(pil_img: Image.Image) -> np.ndarray:
    img = pil_img.convert("RGB").resize(IMG_SIZE)
    arr = np.array(img, dtype=np.float32) / 255.0
    return np.expand_dims(arr, axis=0)

def predict_top3(model, img_arr, class_names):
    proba = model.predict(img_arr, verbose=0)[0]
    top3  = np.argsort(proba)[::-1][:3]
    return [(class_names[i], float(proba[i])) for i in top3]

def predict_top3_tta(model, pil_img: Image.Image, class_names):
    """Test-Time Augmentation: predict trên 5 biến thể → average xác suất."""
    w, h = pil_img.size
    margin_w, margin_h = int(w * 0.1), int(h * 0.1)
    variants = [
        pil_img,
        pil_img.transpose(Image.FLIP_LEFT_RIGHT),
        ImageEnhance.Brightness(pil_img).enhance(1.3),
        ImageEnhance.Brightness(pil_img).enhance(0.7),
        pil_img.crop((margin_w, margin_h, w - margin_w, h - margin_h))
              .resize((w, h), Image.LANCZOS),
    ]
    all_proba = []
    for v in variants:
        arr = np.array(v.convert("RGB").resize(IMG_SIZE), dtype=np.float32) / 255.0
        all_proba.append(model.predict(np.expand_dims(arr, 0), verbose=0)[0])
    avg  = np.mean(all_proba, axis=0)
    top3 = np.argsort(avg)[::-1][:3]
    return [(class_names[i], float(avg[i])) for i in top3]

# ─────────────────────────────────────────────
# Lịch sử — đọc/ghi file history.json
# ─────────────────────────────────────────────
def load_history():
    if not PERSIST_HISTORY or not HISTORY_PATH.exists():
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        entries = json.load(f)
    for e in entries:
        if isinstance(e["thumb"], str):
            e["thumb"] = base64.b64decode(e["thumb"])
    return entries

def save_history(history):
    if not PERSIST_HISTORY:
        return
    serializable = []
    for e in history:
        entry = dict(e)
        if isinstance(entry["thumb"], bytes):
            entry["thumb"] = base64.b64encode(entry["thumb"]).decode("utf-8")
        serializable.append(entry)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)

# ─────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = load_history()

# ─────────────────────────────────────────────
# Khởi tạo model
# ─────────────────────────────────────────────
model                      = load_model()
class_names, nutrition_map = load_metadata()

if model is not None:
    _s = model.input_shape
    IMG_SIZE = (_s[1], _s[2])

# ─────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────
st.title("🍽️ Food Recognition")
st.markdown("**CNN + L2 Regularization** — nhận dạng 20 loại món ăn")

if model is None:
    st.error(
        "⚠️ Không tìm thấy **food_model.h5** trong thư mục hiện tại.\n\n"
        "Hãy đặt `food_model.h5` cùng thư mục với `app.py` rồi chạy lại."
    )
    st.info("Cấu trúc thư mục cần có:\n```\nproject7/\n├── app.py\n├── food_model.h5\n├── class_names.json\n└── Mapping_Calories.json\n```")
    st.stop()

# ─────────────────────────────────────────────
# Upload ảnh
# ─────────────────────────────────────────────
st.divider()
uploaded = st.file_uploader(
    "📁 Tải ảnh món ăn lên (JPG / PNG)",
    type=["jpg", "jpeg", "png"],
    help="Ảnh sẽ được resize về 128×128 để đưa vào model",
)

if uploaded is not None:
    pil_img = Image.open(uploaded)

    col_img, col_result = st.columns([1, 1], gap="large")

    with col_img:
        st.subheader("Ảnh đầu vào")
        st.image(pil_img, use_container_width=True)
        st.caption(f"Kích thước gốc: {pil_img.size[0]} × {pil_img.size[1]} px")

    with col_result:
        st.subheader("Kết quả dự đoán")
        use_tta = st.checkbox(
            "🔬 Dùng TTA (chính xác hơn, chậm hơn ~5×)",
            value=False,
            help="Test-Time Augmentation: predict trên 5 biến thể ảnh rồi lấy trung bình",
        )

        spinner_msg = "🔍 Đang phân tích (TTA × 5)..." if use_tta else "🔍 Đang phân tích ảnh..."
        with st.spinner(spinner_msg):
            if use_tta:
                top3 = predict_top3_tta(model, pil_img, class_names)
            else:
                img_arr = preprocess(pil_img)
                top3    = predict_top3(model, img_arr, class_names)

        best_label, best_conf = top3[0]
        st.success(f"**{pretty(best_label)}**")

        labels = [pretty(lbl) for lbl, _ in top3]
        values = [c * 100 for _, c in top3]

        fig_bar = go.Figure(go.Bar(
            x=values, y=labels, orientation="h",
            marker_color=["#2ecc71", "#f39c12", "#e74c3c"],
            text=[f"{v:.1f}%" for v in values],
            textposition="inside", insidetextanchor="middle",
        ))
        fig_bar.update_layout(
            title="Top-3 dự đoán",
            xaxis=dict(title="Độ tin cậy (%)", range=[0, 100]),
            height=190,
            margin=dict(l=10, r=10, t=40, b=10),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()
    st.subheader("🥗 Thông tin dinh dưỡng")
    info = nutrition_map.get(best_label)

    if info:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🔥 Calories",     f"{info['calories']} kcal")
        c2.metric("🍚 Carbohydrate", f"{info['carbohydrate']} g")
        c3.metric("💪 Protein",      f"{info['protein']} g")
        c4.metric("🫙 Lipid",        f"{info['lipid']} g")

        carb_cal  = info["carbohydrate"] * 4
        prot_cal  = info["protein"]      * 4
        lipid_cal = info["lipid"]        * 9

        fig_pie = go.Figure(go.Pie(
            labels=["Carbohydrate", "Protein", "Lipid"],
            values=[carb_cal, prot_cal, lipid_cal],
            hole=0.45,
            marker_colors=["#3498db", "#2ecc71", "#e67e22"],
            textinfo="label+percent",
        ))
        fig_pie.update_layout(
            title=dict(text="Phân bổ Calories từ Macros", x=0.5),
            height=300,
            margin=dict(l=10, r=10, t=50, b=10),
        )
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info(f"Chưa có dữ liệu dinh dưỡng cho **{pretty(best_label)}**.")

    st.divider()
    conf_pct = best_conf * 100
    if conf_pct >= 80:
        badge, color = "🟢 Cao", "green"
    elif conf_pct >= 50:
        badge, color = "🟡 Trung bình", "orange"
    else:
        badge, color = "🔴 Thấp — kết quả có thể không chính xác", "red"

    st.markdown(f"**Độ tin cậy:** :{color}[{badge}] &nbsp; `{conf_pct:.2f}%`")

    with st.expander("Xem ảnh sau khi resize (128×128)"):
        resized = pil_img.convert("RGB").resize(IMG_SIZE)
        st.image(resized, width=200, caption="Ảnh đưa vào model")

    # Lưu lịch sử
    thumb = pil_img.copy()
    thumb.thumbnail((80, 80))
    buf = io.BytesIO()
    thumb.save(buf, format="PNG")

    if not any(h["filename"] == uploaded.name for h in st.session_state.history):
        st.session_state.history.insert(0, {
            "filename": uploaded.name,
            "label":    best_label,
            "conf":     best_conf,
            "calories": info["calories"] if info else "N/A",
            "thumb":    buf.getvalue(),
            "time":     datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        })
        save_history(st.session_state.history)

else:
    st.info("👆 Tải một ảnh món ăn lên để bắt đầu nhận dạng.")
    with st.expander("📋 Xem danh sách 20 món ăn mô hình có thể nhận dạng"):
        cols = st.columns(4)
        for i, name in enumerate(class_names):
            cols[i % 4].markdown(f"• {pretty(name)}")

# ─────────────────────────────────────────────
# Lịch sử dự đoán
# ─────────────────────────────────────────────
if st.session_state.history:
    st.divider()
    st.subheader("🕘 Lịch sử dự đoán đơn lẻ")

    col_btn, col_count = st.columns([1, 5])
    with col_btn:
        if st.button("🗑️ Xóa tất cả", use_container_width=True):
            st.session_state.history = []
            save_history([])
            st.rerun()
    with col_count:
        st.caption(f"Tổng cộng {len(st.session_state.history)} ảnh đã nhận dạng")

    # Xóa từng mục nếu được yêu cầu
    to_delete = st.session_state.get("_delete_idx", None)
    if to_delete is not None:
        st.session_state.history.pop(to_delete)
        save_history(st.session_state.history)
        st.session_state["_delete_idx"] = None
        st.rerun()

    for idx, entry in enumerate(st.session_state.history):
        c_thumb, c_info, c_del = st.columns([1, 9, 1])
        with c_thumb:
            st.image(entry["thumb"], width=64)
        with c_info:
            cal_str = f"{entry['calories']} kcal" if entry["calories"] != "N/A" else "N/A"
            st.markdown(
                f"**{pretty(entry['label'])}** &nbsp;·&nbsp; "
                f"`{entry['conf']*100:.1f}%` &nbsp;·&nbsp; "
                f"🔥 {cal_str} &nbsp;·&nbsp; "
                f"<span style='color:gray;font-size:12px'>{entry['time']}</span>",
                unsafe_allow_html=True,
            )
        with c_del:
            if st.button("✕", key=f"del_{idx}", help="Xóa mục này"):
                st.session_state["_delete_idx"] = idx
                st.rerun()

# ─────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────
st.divider()
st.markdown(
    "<div style='text-align:center;color:gray;font-size:12px'>"
    "Project 7 &nbsp;·&nbsp; CNN + L2 Regularization &nbsp;·&nbsp; "
    "Python / TensorFlow / Streamlit"
    "</div>",
    unsafe_allow_html=True,
)