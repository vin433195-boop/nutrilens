/* Thư viện món ăn: tự gửi form khi đổi cách sắp xếp hoặc gõ xong từ khóa (lọc và phân trang do server xử lý) */
(function () {
  "use strict";
  const form = document.querySelector("[data-food-filter]");
  if (!form) return;
  const search = form.querySelector("#food-search");
  const sort = form.querySelector("#food-sort");
  let timer = null;

  sort.addEventListener("change", () => form.submit());
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => form.submit(), 600);
  });
  // Giữ con trỏ ở cuối ô tìm kiếm sau khi trang tải lại
  if (search.value) {
    search.focus();
    search.setSelectionRange(search.value.length, search.value.length);
  }
})();
