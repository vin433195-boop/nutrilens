/* Form tài khoản: hiện/ẩn mật khẩu, đo độ mạnh mật khẩu, xác nhận thao tác nguy hiểm */
(function () {
  "use strict";

  document.querySelectorAll("[data-pw-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = btn.parentElement.querySelector("input");
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.setAttribute("aria-label", show ? "Ẩn mật khẩu" : "Hiện mật khẩu");
      btn.style.color = show ? "var(--primary)" : "";
    });
  });

  function strength(pw) {
    let s = 0;
    if (pw.length >= 8) s++;
    if (pw.length >= 12) s++;
    if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s++;
    if (/\d/.test(pw)) s++;
    if (/[^A-Za-z0-9]/.test(pw)) s++;
    return s;
  }
  const colors = ["var(--limit)", "var(--limit)", "var(--ok)", "var(--ok)", "var(--good)", "var(--good)"];
  document.querySelectorAll("[data-pw-meter]").forEach((input) => {
    const bar = input.closest(".field").querySelector(".pw-meter i");
    input.addEventListener("input", () => {
      const s = input.value ? strength(input.value) : 0;
      bar.style.width = (s / 5) * 100 + "%";
      bar.style.background = colors[s];
    });
  });

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!confirm(form.dataset.confirm)) e.preventDefault();
    });
  });
})();
