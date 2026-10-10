/* Nhật ký ăn uống: lưu trên MySQL khi đã đăng nhập, trên trình duyệt khi là khách */
(function () {
  "use strict";
  const root = document.querySelector("[data-diary]");
  if (!root) return;
  const { fmt, diary, toast, escapeHtml } = window.NL;

  const FOODS = Object.fromEntries((window.NL_FOODS || []).map((f) => [f.slug, f]));
  const MEALS = [
    ["breakfast", "Bữa sáng", "🌅"],
    ["lunch", "Bữa trưa", "☀️"],
    ["dinner", "Bữa tối", "🌙"],
    ["snack", "Bữa phụ", "🍎"],
  ];
  const mealsBox = root.querySelector("[data-meals]");
  const dateLabel = root.querySelector("[data-date-label]");
  let current = new Date();
  let entries = [];
  let renderToken = 0;

  const options = Object.values(FOODS)
    .map((f) => `<option value="${f.slug}">${f.emoji} ${escapeHtml(f.name_vi)} · ${fmt.num(f.nutrition.calories)} kcal</option>`).join("");

  const iso = () => fmt.isoDate(current);

  function totals(items) {
    const t = { calories: 0, protein: 0, carb: 0, fat: 0 };
    items.forEach((it) => {
      t.calories += it.kcal * it.servings;
      t.protein += it.protein * it.servings;
      t.carb += it.carb * it.servings;
      t.fat += it.fat * it.servings;
    });
    return t;
  }

  function dateText(d) {
    const base = d.toLocaleDateString("vi-VN", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" });
    if (fmt.isoDate(d) === fmt.isoDate(new Date())) return "Hôm nay, " + base;
    return base.charAt(0).toUpperCase() + base.slice(1);
  }

  async function run(action) {
    try { await action(); } catch (err) { toast(err.message, "error"); }
    await render();
  }

  async function render() {
    const token = ++renderToken;
    dateLabel.textContent = dateText(current);
    let target, week;
    try {
      [entries, target, week] = await Promise.all([diary.day(iso()), diary.target(), diary.week(current)]);
    } catch (err) {
      mealsBox.innerHTML = `<div class="notice error"><span>${escapeHtml(err.message)}</span></div>`;
      return;
    }
    if (token !== renderToken) return; // Người dùng đã chuyển ngày khác trong lúc chờ

    mealsBox.innerHTML = MEALS.map(([key, label, icon]) => {
      const list = entries.filter((it) => it.meal === key);
      const kcal = list.reduce((s, it) => s + it.kcal * it.servings, 0);
      const rows = list.map((it) => `<li>
          <span class="e" aria-hidden="true">${escapeHtml(it.emoji)}</span>
          <div class="info"><strong>${escapeHtml(it.name)}</strong><span>${escapeHtml(it.serving)} · ${fmt.num(it.kcal * it.servings)} kcal</span></div>
          <label class="sr-only" for="q-${it.id}">Số khẩu phần</label>
          <input class="input qty" id="q-${it.id}" type="number" min="0.25" max="20" step="0.25" value="${it.servings}" data-qty="${it.id}">
          <button class="icon-btn" type="button" data-remove="${it.id}" aria-label="Xóa ${escapeHtml(it.name)}" style="width:34px; height:34px">✕</button>
        </li>`).join("");
      return `<div class="meal card">
        <div class="meal-head"><h3><span aria-hidden="true">${icon}</span>${label}</h3><span class="kcal">${fmt.num(kcal)} kcal</span></div>
        ${rows ? `<ul class="meal-items">${rows}</ul>` : `<div class="meal-empty">Chưa có món nào.</div>`}
        <form class="meal-add" data-add="${key}">
          <label class="sr-only" for="add-${key}">Chọn món cho ${label.toLowerCase()}</label>
          <select class="input" id="add-${key}" name="slug">${options}</select>
          <label class="sr-only" for="qty-${key}">Số khẩu phần</label>
          <input class="input qty" id="qty-${key}" name="qty" type="number" min="0.25" max="20" step="0.25" value="1">
          <button class="btn btn-primary btn-sm" type="submit">+ Thêm</button>
        </form>
      </div>`;
    }).join("");

    renderSummary(totals(entries), target);
    renderWeek(week, target.calories);
  }

  function renderSummary(t, target) {
    const pct = Math.min(100, (t.calories / target.calories) * 100);
    const ring = root.querySelector("[data-ring]");
    ring.style.setProperty("--pct", pct);
    ring.classList.toggle("over", t.calories > target.calories);
    root.querySelector("[data-total]").textContent = fmt.num(Math.round(t.calories));
    root.querySelector("[data-target-label]").textContent = `/ ${fmt.num(target.calories)} kcal`;
    const remain = Math.round(target.calories - t.calories);
    root.querySelector("[data-remaining]").innerHTML = remain >= 0
      ? `Còn <b>${fmt.num(remain)} kcal</b> để đạt mục tiêu`
      : `<span style="color:var(--limit)">Vượt <b>${fmt.num(-remain)} kcal</b> so với mục tiêu</span>`;

    const bars = [
      ["Protein", t.protein, target.protein, "dot-protein"],
      ["Carbohydrate", t.carb, target.carb, "dot-carb"],
      ["Chất béo", t.fat, target.fat, "dot-lipid"],
    ];
    root.querySelector("[data-macros]").innerHTML = bars.map(([name, v, goal, cls]) => `
      <div class="macro-bar">
        <div class="top"><span>${name}</span><b>${fmt.num(Math.round(v))} / ${fmt.num(goal)} g</b></div>
        <div class="track"><i class="${cls}" style="width:${goal ? Math.min(100, (v / goal) * 100) : 0}%"></i></div>
      </div>`).join("");
  }

  function renderWeek(days, target) {
    const max = Math.max(target * 1.25, ...days.map((x) => x.kcal));
    const selected = iso();
    root.querySelector("[data-week]").innerHTML = days.map(({ date, kcal }) => {
      const d = new Date(date + "T00:00:00");
      const h = kcal ? Math.max(4, (kcal / max) * 100) : 3;
      const cls = !kcal ? "none" : kcal > target ? "over" : "";
      const label = d.toLocaleDateString("vi-VN", { weekday: "short" });
      return `<div class="col ${date === selected ? "today" : ""}" title="${d.toLocaleDateString("vi-VN")}: ${fmt.num(Math.round(kcal))} kcal">
        <div class="bar-area"><div class="b ${cls}" style="height:${h}%"></div><i class="tline" style="bottom:${(target / max) * 100}%"></i></div>
        <span>${label}</span></div>`;
    }).join("");
  }

  // ── Sự kiện ──
  mealsBox.addEventListener("submit", (e) => {
    const form = e.target.closest("[data-add]");
    if (!form) return;
    e.preventDefault();
    const qty = Math.min(20, Math.max(0.25, Number(form.elements.qty.value) || 1));
    run(() => diary.add(form.elements.slug.value, form.dataset.add, qty, iso()));
  });
  mealsBox.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remove]");
    if (btn) run(() => diary.remove(btn.dataset.remove, iso()));
  });
  mealsBox.addEventListener("change", (e) => {
    const input = e.target.closest("[data-qty]");
    if (!input) return;
    const qty = Math.min(20, Math.max(0.25, Number(input.value) || 1));
    run(() => diary.update(input.dataset.qty, qty, iso()));
  });
  root.querySelectorAll("[data-day]").forEach((btn) => btn.addEventListener("click", () => {
    current.setDate(current.getDate() + Number(btn.dataset.day));
    render();
  }));
  root.querySelector("[data-today]").addEventListener("click", () => { current = new Date(); render(); });
  root.querySelector("[data-clear-day]").addEventListener("click", () => {
    if (confirm("Xóa toàn bộ món ăn của ngày này?")) run(() => diary.clear(iso()));
  });
  document.addEventListener("nl:synced", render);

  // Thêm nhanh từ trang chi tiết món: /nhat-ky?them=pho
  const quick = new URLSearchParams(location.search).get("them");
  history.replaceState(null, "", location.pathname);
  if (quick && FOODS[quick]) {
    run(async () => {
      await diary.add(quick, diary.mealForNow(), 1, iso());
      toast(`Đã thêm ${FOODS[quick].name_vi} vào nhật ký hôm nay.`);
    });
  } else {
    render();
  }
})();
