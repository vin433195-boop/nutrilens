/* Nhận dạng món ăn: chọn ảnh, gọi /api/predict, hiển thị kết quả và lịch sử */
(function () {
  "use strict";
  const root = document.querySelector("[data-recognizer]");
  if (!root) return;
  const { store, fmt, diary, toast, escapeHtml, api, isAuthed } = window.NL;

  const MAX_BYTES = 8 * 1024 * 1024;
  const HISTORY_KEY = "nl-history";
  const MEALS = { breakfast: "Bữa sáng", lunch: "Bữa trưa", dinner: "Bữa tối", snack: "Bữa phụ" };

  const dropzone = root.querySelector("[data-dropzone]");
  const fileInput = root.querySelector("[data-file]");
  const preview = root.querySelector("[data-preview]");
  const analyzeBtn = root.querySelector("[data-analyze]");
  const resetBtn = root.querySelector("[data-reset]");
  const ttaInput = root.querySelector("[data-tta]");
  const resultEmpty = root.querySelector("[data-result-empty]");
  const resultBox = root.querySelector("[data-result]");
  const historyBox = document.querySelector("[data-history]");
  const historyEmpty = document.querySelector("[data-history-empty]");
  const clearHistoryBtn = document.querySelector("[data-clear-history]");
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const modelUnavailable = ["missing", "error"].includes(root.dataset.status);

  let currentFile = null;
  let objectUrl = null;
  let lastPredictions = [];
  let lastRecognitionId = null;
  let lastPicked = 0;

  // ── Chọn ảnh ─────────────────────────────────────────────
  function setFile(file) {
    if (!file) return;
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) { toast("Chỉ hỗ trợ ảnh JPG, PNG hoặc WEBP.", "error"); return; }
    if (file.size > MAX_BYTES) { toast("Ảnh lớn hơn 8 MB, vui lòng chọn ảnh khác.", "error"); return; }
    currentFile = file;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(file);
    preview.src = objectUrl;
    dropzone.classList.add("has-image");
    analyzeBtn.disabled = modelUnavailable;
    resetBtn.hidden = false;
    if (!modelUnavailable) analyze();
  }

  function reset() {
    currentFile = null;
    fileInput.value = "";
    dropzone.classList.remove("has-image", "loading");
    preview.removeAttribute("src");
    analyzeBtn.disabled = true;
    resetBtn.hidden = true;
    resultBox.hidden = true;
    resultEmpty.hidden = false;
  }

  fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
  ["dragenter", "dragover"].forEach((ev) => dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("drag"); }));
  dropzone.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));
  document.addEventListener("paste", (e) => {
    const item = Array.from(e.clipboardData?.items || []).find((i) => i.type.startsWith("image/"));
    if (item) setFile(item.getAsFile());
  });
  resetBtn.addEventListener("click", reset);
  analyzeBtn.addEventListener("click", analyze);
  ttaInput.addEventListener("change", () => { if (currentFile && !modelUnavailable) analyze(); });

  // ── Gọi API ──────────────────────────────────────────────
  async function analyze() {
    if (!currentFile) return;
    const body = new FormData();
    body.append("image", currentFile);
    if (ttaInput.checked) body.append("tta", "1");

    analyzeBtn.disabled = true;
    analyzeBtn.innerHTML = '<span class="spinner"></span> Đang phân tích...';
    dropzone.classList.add("loading");
    try {
      const res = await fetch(root.dataset.endpoint, { method: "POST", body, headers: { "X-CSRF-Token": csrf } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Không phân tích được ảnh.");
      lastPredictions = data.predictions;
      lastRecognitionId = data.recognition_id;
      lastPicked = 0;
      renderResult(0, data.tta);
      try { await history.add(data.predictions[0], thumbnail(), lastRecognitionId); } catch (e) { /* bỏ qua */ }
      renderHistory();
    } catch (err) {
      resultEmpty.hidden = true;
      resultBox.hidden = false;
      resultBox.innerHTML = `<div class="notice error"><span>${escapeHtml(err.message)}</span></div>`;
    } finally {
      dropzone.classList.remove("loading");
      analyzeBtn.disabled = false;
      analyzeBtn.innerHTML = "Phân tích lại";
    }
  }

  // ── Hiển thị kết quả ─────────────────────────────────────
  function renderResult(selected, tta) {
    const top = lastPredictions[0];
    const pick = lastPredictions[selected];
    const f = pick.food;
    const n = f ? f.nutrition : null;
    const pct = (c) => (c * 100).toFixed(1).replace(".", ",");

    const confRows = lastPredictions.map((p, i) => `
      <button type="button" class="conf-item" data-pick="${i}" style="all:unset; display:grid; grid-template-columns:1fr auto; gap:6px 12px; font-size:.92rem; cursor:pointer" aria-pressed="${i === selected}">
        <span>${p.food ? p.food.emoji + " " + escapeHtml(p.food.name_vi) : escapeHtml(p.label)} ${i === selected ? '<span class="badge badge-good" style="margin-left:6px">Đang xem</span>' : ""}</span>
        <b>${pct(p.confidence)}%</b>
        <span class="track" style="grid-column:1/-1; height:10px; border-radius:10px; background:var(--surface-3); overflow:hidden; display:block">
          <i style="display:block; height:100%; border-radius:10px; width:0; background:${["var(--primary)", "var(--ok)", "var(--limit)"][i] || "var(--muted)"}; transition: width .8s" data-w="${p.confidence * 100}"></i>
        </span>
      </button>`).join("");

    const nutrition = f ? `
      <div class="mini-stats">
        <div><strong>${fmt.num(n.calories)}</strong><span>kcal</span></div>
        <div><strong style="color:var(--protein)">${fmt.num(n.protein)}g</strong><span>Protein</span></div>
        <div><strong style="color:var(--carb)">${fmt.num(n.carbohydrate)}g</strong><span>Carb</span></div>
        <div><strong style="color:var(--lipid)">${fmt.num(n.lipid)}g</strong><span>Chất béo</span></div>
      </div>
      <div class="donut-wrap" style="margin-bottom:18px">
        <div class="donut sm" style="--c:${f.macro_percent.carbohydrate}; --p:${f.macro_percent.protein}"><div class="donut-center"><strong>${fmt.num(n.calories)}</strong><span>kcal</span></div></div>
        <ul class="legend">
          <li><i class="dot-carb"></i>Carbohydrate <b>${f.macro_percent.carbohydrate}%</b></li>
          <li><i class="dot-protein"></i>Protein <b>${f.macro_percent.protein}%</b></li>
          <li><i class="dot-lipid"></i>Chất béo <b>${f.macro_percent.lipid}%</b></li>
        </ul>
      </div>
      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center">
        <label class="sr-only" for="meal-pick">Bữa ăn</label>
        <select class="input" id="meal-pick" style="width:auto">${Object.entries(MEALS).map(([k, v]) => `<option value="${k}" ${k === diary.mealForNow() ? "selected" : ""}>${v}</option>`).join("")}</select>
        <button class="btn btn-primary" type="button" data-add-diary>+ Thêm vào nhật ký</button>
        <a class="btn btn-outline" href="${f.url}">Chi tiết món</a>
      </div>` : `<div class="notice">Chưa có dữ liệu dinh dưỡng cho món này.</div>`;

    const lowConfidence = top.level === "low"
      ? `<div class="notice warn" style="margin-bottom:16px"><span>Độ tin cậy thấp. Hãy thử bật chế độ chính xác cao, chụp lại gần hơn hoặc chọn dự đoán phù hợp bên dưới.</span></div>` : "";

    resultBox.innerHTML = `
      <div class="result-top">
        <div class="e" aria-hidden="true">${f ? f.emoji : "🍽️"}</div>
        <div>
          <span class="badge badge-${pick.level}">Độ tin cậy ${pick.level_vi.toLowerCase()} · ${pct(pick.confidence)}%</span>
          <h2>${f ? escapeHtml(f.name_vi) : escapeHtml(pick.label)}</h2>
          <span class="muted small">${f ? escapeHtml(f.name_en) + " · " + escapeHtml(f.serving) : ""}${tta ? " · Đã dùng TTA" : ""}</span>
        </div>
      </div>
      ${lowConfidence}
      <h3 style="font-size:1rem; margin-bottom:4px">Top-3 dự đoán</h3>
      <p class="muted small" style="margin:0">Bấm vào một dự đoán nếu đó mới là món đúng.</p>
      <div class="conf-list">${confRows}</div>
      ${nutrition}`;
    resultEmpty.hidden = true;
    resultBox.hidden = false;
    requestAnimationFrame(() => resultBox.querySelectorAll("[data-w]").forEach((el) => { el.style.width = el.dataset.w + "%"; }));

    resultBox.querySelectorAll("[data-pick]").forEach((btn) => btn.addEventListener("click", () => {
      const idx = Number(btn.dataset.pick);
      renderResult(idx, tta);
      if (idx !== lastPicked) {
        lastPicked = idx;
        // Ghi nhận món người dùng chọn lại: dữ liệu để cải thiện model sau này
        history.correct(lastRecognitionId, lastPredictions[idx]).then(renderHistory).catch(() => {});
      }
    }));
    const addBtn = resultBox.querySelector("[data-add-diary]");
    if (addBtn) addBtn.addEventListener("click", async () => {
      const meal = resultBox.querySelector("#meal-pick").value;
      addBtn.disabled = true;
      try {
        await diary.add(f.slug, meal, 1, fmt.isoDate(new Date()));
        toast(`Đã thêm ${f.name_vi} vào ${MEALS[meal].toLowerCase()} hôm nay.`);
      } catch (err) {
        toast(err.message, "error");
      } finally {
        addBtn.disabled = false;
      }
    });
  }

  // ── Lịch sử nhận dạng ────────────────────────────────────
  // Đã đăng nhập: kết quả lưu trên máy chủ, ảnh thu nhỏ chỉ lưu trên thiết bị này.
  // Khách: toàn bộ lưu trên trình duyệt.
  const THUMBS_KEY = "nl-thumbs";
  function thumbnail() {
    try {
      const size = 96;
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = size;
      const ctx = canvas.getContext("2d");
      const s = Math.min(preview.naturalWidth, preview.naturalHeight);
      ctx.drawImage(preview, (preview.naturalWidth - s) / 2, (preview.naturalHeight - s) / 2, s, s, 0, 0, size, size);
      return canvas.toDataURL("image/jpeg", 0.7);
    } catch (e) { return ""; }
  }
  const toItem = (pred) => ({
    slug: pred.food ? pred.food.slug : pred.label,
    name: pred.food ? pred.food.name_vi : pred.label,
    emoji: pred.food ? pred.food.emoji : "🍽️",
    kcal: pred.food ? pred.food.nutrition.calories : null,
  });

  const localHistory = {
    async list() { return store.get(HISTORY_KEY, []).map((h, i) => ({ ...h, key: i })); },
    async add(pred, thumb) {
      const list = store.get(HISTORY_KEY, []);
      list.unshift({ ...toItem(pred), thumb, conf: pred.confidence, time: new Date().toLocaleString("vi-VN") });
      store.set(HISTORY_KEY, list.slice(0, 12));
    },
    async correct(_id, pred) {
      const list = store.get(HISTORY_KEY, []);
      if (list.length) { Object.assign(list[0], toItem(pred), { corrected: true }); store.set(HISTORY_KEY, list); }
    },
    async remove(key) { const l = store.get(HISTORY_KEY, []); l.splice(Number(key), 1); store.set(HISTORY_KEY, l); },
    async clear() { store.set(HISTORY_KEY, []); },
  };

  const serverHistory = {
    async list() {
      const thumbs = store.get(THUMBS_KEY, {});
      return (await api("GET", "/api/recognitions")).items.map((h) => ({
        ...h, key: h.id, conf: h.confidence, thumb: thumbs[h.id] || "", time: new Date(h.time).toLocaleString("vi-VN"),
      }));
    },
    async add(_pred, thumb, id) {
      if (!id || !thumb) return;
      const thumbs = store.get(THUMBS_KEY, {});
      thumbs[id] = thumb;
      const keep = Object.keys(thumbs).map(Number).sort((a, b) => b - a).slice(0, 12);
      store.set(THUMBS_KEY, Object.fromEntries(keep.map((k) => [k, thumbs[k]])));
    },
    async correct(id, pred) { if (id && pred.food) await api("PATCH", `/api/recognitions/${id}`, { slug: pred.food.slug }); },
    async remove(id) { await api("DELETE", `/api/recognitions/${id}`); },
    async clear() { await api("DELETE", "/api/recognitions"); store.set(THUMBS_KEY, {}); },
  };
  const history = isAuthed ? serverHistory : localHistory;

  async function renderHistory() {
    let list = [];
    try { list = await history.list(); } catch (err) { historyEmpty.textContent = err.message; }
    historyEmpty.hidden = list.length > 0;
    clearHistoryBtn.hidden = list.length === 0;
    historyBox.innerHTML = list.map((h) => `
      <div class="history-item">
        ${h.thumb && h.thumb.startsWith("data:image/") ? `<img src="${h.thumb}" alt="">` : `<span style="font-size:2rem; width:52px; text-align:center">${escapeHtml(h.emoji)}</span>`}
        <div class="info">
          <strong><a href="/mon-an/${encodeURIComponent(h.slug)}" style="color:inherit">${escapeHtml(h.name)}</a>${h.corrected ? ' <span class="badge" title="Bạn đã chọn lại món này">đã sửa</span>' : ""}</strong>
          <span>${(h.conf * 100).toFixed(1).replace(".", ",")}% · ${h.kcal != null ? fmt.num(h.kcal) + " kcal · " : ""}${escapeHtml(h.time)}</span>
        </div>
        <button class="icon-btn" type="button" data-del="${escapeHtml(h.key)}" aria-label="Xóa mục này" style="width:32px; height:32px">✕</button>
      </div>`).join("");
    historyBox.querySelectorAll("[data-del]").forEach((btn) => btn.addEventListener("click", async () => {
      try { await history.remove(btn.dataset.del); } catch (err) { toast(err.message, "error"); }
      renderHistory();
    }));
  }

  clearHistoryBtn.addEventListener("click", async () => {
    try { await history.clear(); } catch (err) { toast(err.message, "error"); }
    renderHistory();
  });
  renderHistory();
})();
