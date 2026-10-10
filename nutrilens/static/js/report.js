/* Báo cáo: biểu đồ calo theo ngày (cột), cân nặng (đường), macro trung bình. SVG thuần, có tooltip khi rê chuột. */
(function () {
  "use strict";
  const root = document.querySelector("[data-report]");
  if (!root) return;
  const { api, fmt, toast, escapeHtml } = window.NL;
  const $ = (sel) => root.querySelector(sel);
  const SVGNS = "http://www.w3.org/2000/svg";
  let range = 30;

  const dayLabel = (iso, opts = { day: "2-digit", month: "2-digit" }) =>
    new Date(iso + "T00:00:00").toLocaleDateString("vi-VN", opts);

  // ── Tooltip dùng chung ──
  const tip = document.createElement("div");
  tip.className = "chart-tip";
  tip.hidden = true;
  document.body.appendChild(tip);
  function showTip(html, evt) {
    tip.innerHTML = html;
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let x = evt.clientX + 14, y = evt.clientY - r.height - 12;
    if (x + r.width > window.innerWidth - 8) x = evt.clientX - r.width - 14;
    if (y < 8) y = evt.clientY + 16;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  const hideTip = () => { tip.hidden = true; };

  function el(name, attrs = {}, parent) {
    const node = document.createElementNS(SVGNS, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }

  function niceMax(v) {
    if (v <= 0) return 1;
    const p = 10 ** Math.floor(Math.log10(v));
    return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v);
  }

  // ── Biểu đồ cột: calo mỗi ngày + đường mục tiêu ──
  function kcalChart(days, target) {
    const box = $("[data-kcal-chart]");
    box.innerHTML = "";
    const W = 760, H = 260, L = 44, R = 12, T = 14, B = 26;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `Biểu đồ cột calo mỗi ngày trong ${days.length} ngày, mục tiêu ${target} kcal` }, box);
    const max = niceMax(Math.max(target * 1.2, ...days.map((d) => d.kcal)));
    const y = (v) => T + (H - T - B) * (1 - v / max);
    const step = (W - L - R) / days.length;
    const barW = Math.max(3, step - 2); // Khe 2px giữa các cột

    [0, max / 2, max].forEach((v) => {
      el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid-line" }, svg);
      el("text", { x: L - 8, y: y(v) + 4, class: "axis-label", "text-anchor": "end" }, svg).textContent = fmt.num(v);
    });
    const labelEvery = days.length > 31 ? 14 : days.length > 10 ? 5 : 1;
    days.forEach((d, i) => {
      const x = L + i * step + 1;
      if (d.kcal > 0) {
        const h = Math.max(2, y(0) - y(d.kcal));
        const r = Math.min(4, barW / 2, h);
        // Cột bo tròn 4px ở đầu, góc vuông ở đáy
        el("path", { class: "bar", d: `M${x},${y(0)} V${y(0) - h + r} Q${x},${y(0) - h} ${x + r},${y(0) - h} H${x + barW - r} Q${x + barW},${y(0) - h} ${x + barW},${y(0) - h + r} V${y(0)} Z` }, svg);
      }
      if ((days.length - 1 - i) % labelEvery === 0) {
        el("text", { x: x + barW / 2, y: H - 8, class: "axis-label", "text-anchor": "middle" }, svg).textContent = dayLabel(d.date);
      }
      // Vùng rê chuột rộng hơn cột
      const hit = el("rect", { x: L + i * step, y: T, width: step, height: H - T - B, class: "hit" }, svg);
      const diff = d.kcal - target;
      const html = `<strong>${dayLabel(d.date, { weekday: "short", day: "2-digit", month: "2-digit" })}</strong>`
        + (d.kcal ? `<div>${fmt.num(d.kcal)} kcal</div><div class="muted">${diff > 0 ? "Vượt" : "Còn thiếu"} ${fmt.num(Math.abs(diff))} kcal so với mục tiêu</div>`
                  : `<div class="muted">Chưa ghi nhật ký</div>`);
      hit.addEventListener("mousemove", (e) => showTip(html, e));
      hit.addEventListener("mouseleave", hideTip);
    });
    el("line", { x1: L, x2: W - R, y1: y(target), y2: y(target), class: "target-line" }, svg);
    el("text", { x: W - R, y: y(target) - 6, class: "axis-label strong", "text-anchor": "end" }, svg).textContent = `Mục tiêu ${fmt.num(target)}`;
  }

  // ── Biểu đồ đường: cân nặng ──
  function weightChart(points) {
    const box = $("[data-weight-chart]");
    box.innerHTML = "";
    if (points.length < 2) {
      box.innerHTML = `<div class="empty" style="padding:28px 12px"><p>${points.length ? "Ghi thêm ít nhất một ngày nữa để xem xu hướng." : "Chưa có dữ liệu cân nặng. Hãy ghi cân nặng đầu tiên ở ô phía trên."}</p></div>`;
      return;
    }
    const W = 760, H = 220, L = 44, R = 16, T = 16, B = 26;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Biểu đồ đường cân nặng theo thời gian" }, box);
    const ws = points.map((p) => p.weight);
    const lo = Math.floor(Math.min(...ws) - 1), hi = Math.ceil(Math.max(...ws) + 1);
    const t0 = new Date(points[0].date).getTime(), t1 = new Date(points[points.length - 1].date).getTime();
    const x = (iso) => L + (W - L - R) * ((new Date(iso).getTime() - t0) / Math.max(1, t1 - t0));
    const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
    [lo, (lo + hi) / 2, hi].forEach((v) => {
      el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid-line" }, svg);
      el("text", { x: L - 8, y: y(v) + 4, class: "axis-label", "text-anchor": "end" }, svg).textContent = fmt.num(v, 1);
    });
    el("text", { x: L, y: H - 8, class: "axis-label" }, svg).textContent = dayLabel(points[0].date);
    el("text", { x: W - R, y: H - 8, class: "axis-label", "text-anchor": "end" }, svg).textContent = dayLabel(points[points.length - 1].date);
    el("polyline", { class: "line", points: points.map((p) => `${x(p.date)},${y(p.weight)}`).join(" ") }, svg);
    const cross = el("line", { y1: T, y2: H - B, class: "crosshair", visibility: "hidden" }, svg);
    const dots = points.map((p) => el("circle", { cx: x(p.date), cy: y(p.weight), r: 4, class: "dot" }, svg));
    const overlay = el("rect", { x: L, y: T, width: W - L - R, height: H - T - B, class: "hit" }, svg);
    overlay.addEventListener("mousemove", (e) => {
      const pt = svg.createSVGPoint();
      pt.x = e.clientX; pt.y = e.clientY;
      const sx = pt.matrixTransform(svg.getScreenCTM().inverse()).x;
      let best = 0;
      points.forEach((p, i) => { if (Math.abs(x(p.date) - sx) < Math.abs(x(points[best].date) - sx)) best = i; });
      const p = points[best];
      cross.setAttribute("x1", x(p.date)); cross.setAttribute("x2", x(p.date)); cross.setAttribute("visibility", "visible");
      dots.forEach((d, i) => d.classList.toggle("active", i === best));
      showTip(`<strong>${dayLabel(p.date, { day: "2-digit", month: "2-digit", year: "numeric" })}</strong><div>${fmt.num(p.weight, 1)} kg</div>`, e);
    });
    overlay.addEventListener("mouseleave", () => { hideTip(); cross.setAttribute("visibility", "hidden"); dots.forEach((d) => d.classList.remove("active")); });
  }

  function renderKpis(r) {
    const avg = r.average.kcal;
    const diff = avg - r.target.calories;
    const tiles = [
      ["Calo trung bình mỗi ngày", r.logged_days ? fmt.num(Math.round(avg)) : "–", r.logged_days ? `${diff >= 0 ? "+" : "−"}${fmt.num(Math.abs(Math.round(diff)))} so với mục tiêu ${fmt.num(r.target.calories)}` : "Chưa có dữ liệu"],
      ["Số ngày đã ghi", `${r.logged_days}/${r.days.length}`, "ngày có ít nhất một món"],
      ["Ngày đạt mục tiêu", r.logged_days ? `${Math.round((r.within_target / r.logged_days) * 100)}%` : "–", "chênh lệch không quá 10%"],
      ["Protein trung bình", r.logged_days ? `${fmt.num(Math.round(r.average.protein))} g` : "–", `mục tiêu ${fmt.num(r.target.protein)} g`],
    ];
    $("[data-kpis]").innerHTML = tiles.map(([label, value, sub]) =>
      `<div class="kpi"><span>${label}</span><strong>${value}</strong><small>${sub}</small></div>`).join("");
  }

  function renderMacros(r) {
    const rows = [["Protein", r.average.protein, r.target.protein, "dot-protein"], ["Carbohydrate", r.average.carb, r.target.carb, "dot-carb"], ["Chất béo", r.average.fat, r.target.fat, "dot-lipid"]];
    $("[data-macro-avg]").innerHTML = rows.map(([name, v, goal, cls]) => `
      <div class="macro-bar"><div class="top"><span>${name}</span><b>${fmt.num(Math.round(v))} / ${fmt.num(goal)} g</b></div>
      <div class="track"><i class="${cls}" style="width:${goal ? Math.min(100, (v / goal) * 100) : 0}%"></i></div></div>`).join("");
    $("[data-top-foods]").innerHTML = r.top_foods.length
      ? r.top_foods.map((f) => `<li><span>${escapeHtml(f.name)}</span><small class="muted">${f.count} lần · ${fmt.num(f.kcal)} kcal</small></li>`).join("")
      : `<li class="muted">Chưa có dữ liệu. <a href="/nhat-ky">Ghi bữa ăn đầu tiên</a>.</li>`;
  }

  function renderTable(days) {
    $("[data-kcal-table]").innerHTML = days.slice().reverse().filter((d) => d.kcal > 0).map((d) =>
      `<tr><td>${dayLabel(d.date, { weekday: "short", day: "2-digit", month: "2-digit" })}</td><td class="num">${fmt.num(d.kcal)}</td><td class="num">${fmt.num(d.protein, 1)} g</td><td class="num">${fmt.num(d.carb, 1)} g</td><td class="num">${fmt.num(d.fat, 1)} g</td></tr>`).join("")
      || `<tr><td colspan="5" class="muted center">Chưa có dữ liệu.</td></tr>`;
  }

  function renderWeights(items) {
    weightChart(items);
    const last = items[items.length - 1], first = items[0];
    $("[data-weight-caption]").textContent = items.length >= 2
      ? `Từ ${fmt.num(first.weight, 1)} kg (${dayLabel(first.date)}) đến ${fmt.num(last.weight, 1)} kg (${dayLabel(last.date)}): ${last.weight - first.weight >= 0 ? "tăng" : "giảm"} ${fmt.num(Math.abs(last.weight - first.weight), 1)} kg.`
      : "";
    $("[data-weight-list]").innerHTML = items.slice(-6).reverse().map((w) =>
      `<span class="chip-photo">${dayLabel(w.date)} · <b>${fmt.num(w.weight, 1)} kg</b><button type="button" data-del-weight="${w.id}" aria-label="Xóa cân nặng ngày ${dayLabel(w.date)}">✕</button></span>`).join("");
  }

  async function load() {
    try {
      const [r, w] = await Promise.all([api("GET", `/api/report?days=${range}`), api("GET", "/api/weights")]);
      renderKpis(r);
      kcalChart(r.days, r.target.calories);
      $("[data-kcal-caption]").textContent = r.logged_days
        ? `Đã ghi ${r.logged_days} trong ${r.days.length} ngày. Rê chuột lên cột để xem chi tiết.`
        : "Chưa có dữ liệu trong khoảng này. Hãy ghi bữa ăn trong Nhật ký.";
      renderMacros(r);
      renderTable(r.days);
      renderWeights(w.items);
    } catch (err) { toast(err.message, "error"); }
  }

  root.querySelectorAll("[data-range]").forEach((btn) => btn.addEventListener("click", () => {
    range = Number(btn.dataset.range);
    root.querySelectorAll("[data-range]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    load();
  }));
  const wForm = $("[data-weight-form]");
  wForm.elements.date.value = fmt.isoDate(new Date());
  wForm.elements.date.max = fmt.isoDate(new Date());
  wForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("POST", "/api/weights", { date: wForm.elements.date.value, weight: wForm.elements.weight.value });
      wForm.elements.weight.value = "";
      toast("Đã ghi cân nặng.");
      load();
    } catch (err) { toast(err.message, "error"); }
  });
  $("[data-weight-list]").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-del-weight]");
    if (!btn) return;
    try { await api("DELETE", `/api/weights/${btn.dataset.delWeight}`); load(); } catch (err) { toast(err.message, "error"); }
  });
  load();
})();
