/* NutriLens — tiện ích dùng chung cho mọi trang */
(function () {
  "use strict";

  // ── Lưu trữ an toàn: localStorage có thể bị chặn (chế độ ẩn danh, chính sách trình duyệt) ──
  const store = {
    get(key, fallback) {
      try {
        const raw = localStorage.getItem(key);
        return raw === null ? fallback : JSON.parse(raw);
      } catch (e) { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
    },
  };

  const fmt = {
    num(v, digits = 0) {
      return Number(v).toLocaleString("vi-VN", { maximumFractionDigits: digits });
    },
    isoDate(d) {
      const z = (n) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
    },
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ── Gọi API JSON (kèm CSRF token) ──
  const isAuthed = document.body.dataset.auth === "1";
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  async function api(method, url, body) {
    const opts = { method, credentials: "same-origin", headers: { "X-CSRF-Token": csrfMeta ? csrfMeta.content : "" } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Không kết nối được máy chủ, vui lòng thử lại.");
    return data;
  }

  // ── Nhật ký ăn uống ──
  // Đã đăng nhập: lưu trong MySQL qua API. Khách: lưu trong localStorage của trình duyệt.
  // Mọi hàm đều trả về Promise để trang dùng giống nhau ở cả hai chế độ.
  const DIARY_KEY = "nl-diary";
  const TARGET_KEY = "nl-target";
  const DEFAULT_TARGET = { calories: 2000, protein: 75, carb: 250, fat: 67 };
  const foodsBySlug = () => Object.fromEntries((window.NL_FOODS || []).map((f) => [f.slug, f]));

  // Đổi lượng nhập (số khẩu phần, hoặc {grams}) sang số khẩu phần
  function toServings(amount, food) {
    if (amount && typeof amount === "object" && amount.grams) {
      if (!food || !food.serving_grams) throw new Error("Món này chưa có khối lượng khẩu phần nên không nhập theo gram được.");
      return Math.max(0.25, Math.round((amount.grams / food.serving_grams) * 100) / 100);
    }
    return Math.min(20, Math.max(0.25, Number(amount) || 1));
  }

  const localDiary = {
    _all() { return store.get(DIARY_KEY, {}); },
    _save(date, items) {
      const data = this._all();
      if (items.length) data[date] = items; else delete data[date];
      if (!store.set(DIARY_KEY, data)) throw new Error("Trình duyệt không cho phép lưu dữ liệu.");
    },
    _raw(date) { return this._all()[date] || []; },
    async day(date) {
      const foods = foodsBySlug();
      return this._raw(date).filter((it) => foods[it.slug]).map((it) => {
        const f = foods[it.slug], n = f.nutrition;
        return { id: it.id, slug: f.slug, name: f.name_vi, emoji: f.emoji, image: f.image, serving: f.serving,
                 serving_grams: f.serving_grams, meal: it.meal,
                 servings: it.qty, kcal: n.calories, carb: n.carbohydrate, protein: n.protein, fat: n.lipid };
      });
    },
    async add(ref, meal, amount, date) {
      const slug = typeof ref === "string" ? ref : ref.slug;
      if (!slug) throw new Error("Món tự thêm chỉ dùng được khi đã đăng nhập.");
      const items = this._raw(date);
      items.push({ id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), slug, meal,
                   qty: toServings(amount, foodsBySlug()[slug]) });
      this._save(date, items);
    },
    async update(id, amount, date) {
      this._save(date, this._raw(date).map((it) => (it.id === id ? { ...it, qty: toServings(amount, foodsBySlug()[it.slug]) } : it)));
    },
    async remove(id, date) { this._save(date, this._raw(date).filter((it) => it.id !== id)); },
    async clear(date) { this._save(date, []); },
    async week(end, days = 7) {
      const foods = foodsBySlug(), all = this._all(), out = [];
      for (let i = days - 1; i >= 0; i--) {
        const d = new Date(end); d.setDate(d.getDate() - i);
        const iso = fmt.isoDate(d);
        const kcal = (all[iso] || []).reduce((s, it) => s + (foods[it.slug] ? foods[it.slug].nutrition.calories * it.qty : 0), 0);
        out.push({ date: iso, kcal });
      }
      return out;
    },
    async target() { return store.get(TARGET_KEY, DEFAULT_TARGET); },
    async setTarget(target, body) {
      if (!store.set(TARGET_KEY, target)) throw new Error("Trình duyệt không cho phép lưu dữ liệu.");
      if (body) store.set("nl-profile", body);
    },
  };

  const serverDiary = {
    async day(date) { return (await api("GET", `/api/diary?date=${date}`)).entries; },
    async add(ref, meal, amount, date) {
      const body = { meal, date, ...(typeof ref === "string" ? { slug: ref } : ref) };
      if (amount && typeof amount === "object" && amount.grams) body.grams = amount.grams;
      else body.servings = Number(amount) || 1;
      await api("POST", "/api/diary", body);
    },
    async update(id, amount) {
      const body = amount && typeof amount === "object" && amount.grams ? { grams: amount.grams } : { servings: Number(amount) || 1 };
      await api("PATCH", `/api/diary/${id}`, body);
    },
    async remove(id) { await api("DELETE", `/api/diary/${id}`); },
    async clear(date) { await api("DELETE", `/api/diary?date=${date}`); },
    async week(end, days = 7) { return (await api("GET", `/api/diary/summary?end=${fmt.isoDate(end)}&days=${days}`)).days; },
    async target() { return (await api("GET", "/api/profile")).target; },
    async setTarget(target, body) { await api("PUT", "/api/profile", { target, body }); },
  };

  const diary = Object.assign(Object.create(isAuthed ? serverDiary : localDiary), {
    mode: isAuthed ? "server" : "local",
    mealForNow() {
      const h = new Date().getHours();
      if (h < 10) return "breakfast";
      if (h < 14) return "lunch";
      if (h < 17) return "snack";
      return "dinner";
    },
  });

  // ── Thông báo nhỏ dạng toast ──
  function toast(message, kind = "success") {
    let wrap = document.querySelector(".flash-wrap");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.className = "flash-wrap";
      wrap.setAttribute("role", "status");
      document.body.appendChild(wrap);
    }
    const el = document.createElement("div");
    el.className = `flash flash-${kind}`;
    el.innerHTML = `<span>${escapeHtml(message)}</span><button type="button" data-dismiss aria-label="Đóng">✕</button>`;
    wrap.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }

  // Ảnh món ăn (nếu có) hoặc emoji dự phòng. Chỉ nhận đường dẫn nội bộ /static/ để tránh chèn URL lạ.
  function foodThumb(item, cls = "e") {
    if (item && typeof item.image === "string" && item.image.startsWith("/static/")) {
      return `<img class="${cls}" src="${escapeHtml(item.image)}" alt="" loading="lazy">`;
    }
    return `<span class="${cls}" aria-hidden="true">${escapeHtml((item && item.emoji) || "🍽️")}</span>`;
  }

  window.NL = { store, fmt, diary, toast, escapeHtml, api, isAuthed, foodThumb };

  // ── Giao diện sáng/tối ──
  document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const root = document.documentElement;
      const current = root.getAttribute("data-theme") ||
        (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = current === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("nl-theme", next); } catch (e) { /* bỏ qua */ }
    });
  });

  // ── Menu trên điện thoại ──
  const navToggle = document.querySelector("[data-nav-toggle]");
  if (navToggle) {
    navToggle.addEventListener("click", () => {
      const open = document.body.classList.toggle("nav-open");
      navToggle.setAttribute("aria-expanded", String(open));
      navToggle.setAttribute("aria-label", open ? "Đóng menu" : "Mở menu");
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && document.body.classList.contains("nav-open")) {
        document.body.classList.remove("nav-open");
        navToggle.setAttribute("aria-expanded", "false");
        navToggle.focus();
      }
    });
  }

  // ── Đóng thông báo ──
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-dismiss]");
    if (btn) btn.closest(".flash")?.remove();
  });
  setTimeout(() => document.querySelectorAll(".flash-wrap .flash").forEach((f) => f.remove()), 6000);

  // ── Hiệu ứng xuất hiện khi cuộn ──
  const reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) { entry.target.classList.add("in"); io.unobserve(entry.target); }
      });
    }, { rootMargin: "0px 0px -40px 0px" });
    reveals.forEach((el) => io.observe(el));
  } else {
    reveals.forEach((el) => el.classList.add("in"));
  }

  // ── Form tự gửi khi đổi lựa chọn (trang so sánh) ──
  document.querySelectorAll("form[data-autosubmit]").forEach((form) => {
    form.addEventListener("change", () => form.submit());
  });

  // ── Lọc bài viết theo chủ đề ──
  const articleFilter = document.querySelector("[data-article-filter]");
  if (articleFilter) {
    const chips = articleFilter.querySelectorAll(".chip");
    chips.forEach((chip) => chip.addEventListener("click", () => {
      chips.forEach((c) => c.classList.toggle("active", c === chip));
      const cat = chip.dataset.category;
      articleFilter.querySelectorAll(".article-card").forEach((card) => {
        card.hidden = Boolean(cat) && card.dataset.category !== cat;
      });
    }));
  }

  // ── Đóng menu tài khoản khi bấm ra ngoài hoặc nhấn Esc ──
  const userMenu = document.querySelector("[data-user-menu]");
  if (userMenu) {
    document.addEventListener("click", (e) => { if (!userMenu.contains(e.target)) userMenu.open = false; });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") userMenu.open = false; });
  }

  // ── Sau khi đăng nhập: chuyển nhật ký và mục tiêu đang lưu trên trình duyệt lên tài khoản ──
  if (isAuthed) {
    const entries = store.get(DIARY_KEY, null);
    const target = store.get(TARGET_KEY, null);
    if ((entries && Object.keys(entries).length) || target) {
      api("POST", "/api/diary/import", { entries: entries || {}, target })
        .then((r) => {
          try { localStorage.removeItem(DIARY_KEY); localStorage.removeItem(TARGET_KEY); } catch (e) { /* bỏ qua */ }
          if (r.imported) toast(`Đã chuyển ${r.imported} món từ nhật ký trên trình duyệt vào tài khoản của bạn.`);
          document.dispatchEvent(new CustomEvent("nl:synced"));
        })
        .catch(() => { /* thử lại ở lần tải trang sau */ });
    }
  }

  // ── Nút yêu thích (trang chi tiết món) ──
  document.querySelectorAll("[data-favorite]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const on = btn.getAttribute("aria-pressed") !== "true";
      btn.disabled = true;
      try {
        await api(on ? "POST" : "DELETE", `/api/favorites/${encodeURIComponent(btn.dataset.favorite)}`);
        btn.setAttribute("aria-pressed", String(on));
        btn.classList.toggle("is-fav", on);
        btn.querySelector("span").textContent = on ? "Đã yêu thích" : "Yêu thích";
        toast(on ? "Đã thêm vào món yêu thích." : "Đã bỏ khỏi món yêu thích.");
      } catch (err) { toast(err.message, "error"); }
      btn.disabled = false;
    });
  });
})();
