/* Thư viện món ăn: tìm kiếm, lọc danh mục, sắp xếp phía trình duyệt */
(function () {
  "use strict";
  const root = document.querySelector("[data-food-filter]");
  if (!root) return;

  const grid = root.querySelector("[data-grid]");
  const cards = Array.from(grid.querySelectorAll(".food-card"));
  const search = root.querySelector("#food-search");
  const sort = root.querySelector("#food-sort");
  const chips = root.querySelectorAll(".chip[data-category]");
  const empty = root.querySelector("[data-empty]");
  const count = root.querySelector("[data-count]");

  const params = new URLSearchParams(location.search);
  let category = params.get("danh-muc") || "";

  // Bỏ dấu tiếng Việt để tìm "pho" vẫn ra "phở"
  const normalize = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d");

  const sorters = {
    name: (a, b) => a.dataset.title.localeCompare(b.dataset.title, "vi"),
    "cal-asc": (a, b) => a.dataset.calories - b.dataset.calories,
    "cal-desc": (a, b) => b.dataset.calories - a.dataset.calories,
    protein: (a, b) => b.dataset.protein - a.dataset.protein,
    score: (a, b) => b.dataset.score - a.dataset.score,
  };

  function syncUrl() {
    const p = new URLSearchParams();
    if (search.value.trim()) p.set("q", search.value.trim());
    if (category) p.set("danh-muc", category);
    const qs = p.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }

  function apply() {
    const q = normalize(search.value.trim());
    let visible = 0;
    cards.sort(sorters[sort.value] || sorters.name).forEach((card) => {
      const ok = (!category || card.dataset.category === category) &&
                 (!q || normalize(card.dataset.name).includes(q));
      card.hidden = !ok;
      card.classList.add("in");
      if (ok) visible++;
      grid.appendChild(card);
    });
    chips.forEach((c) => c.classList.toggle("active", c.dataset.category === category));
    empty.hidden = visible > 0;
    count.textContent = `Hiển thị ${visible} / ${cards.length} món`;
    syncUrl();
  }

  search.addEventListener("input", apply);
  sort.addEventListener("change", apply);
  chips.forEach((chip) => chip.addEventListener("click", () => { category = chip.dataset.category; apply(); }));
  apply();
})();
