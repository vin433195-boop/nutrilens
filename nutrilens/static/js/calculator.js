/* Công cụ tính BMI, BMR (Mifflin-St Jeor), TDEE, calo mục tiêu, macro và lượng nước */
(function () {
  "use strict";
  const form = document.querySelector("[data-calc-form]");
  if (!form) return;
  const { store, fmt, diary, toast } = window.NL;
  const out = (name) => document.querySelector(`[data-out="${name}"]`);
  const errorBox = form.querySelector("[data-calc-error]");
  const saveBtn = document.querySelector("[data-save-target]");
  const PROFILE_KEY = "nl-profile";
  let latest = null;

  // Khôi phục thông tin: ưu tiên hồ sơ trong tài khoản, sau đó là lần nhập trước trên trình duyệt
  const serverBody = window.NL_PROFILE && window.NL_PROFILE.body;
  const saved = serverBody && serverBody.weight
    ? Object.fromEntries(Object.entries(serverBody).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => [k, String(v)]))
    : store.get(PROFILE_KEY, null);
  if (saved) {
    Object.entries(saved).forEach(([k, v]) => {
      const el = form.elements[k];
      if (!el) return;
      if (el instanceof RadioNodeList) { form.querySelector(`input[name="${k}"][value="${v}"]`)?.click(); }
      else el.value = v;
    });
  }

  function bmiCategory(bmi) {
    // Ngưỡng WHO cho người trưởng thành châu Á
    if (bmi < 18.5) return ["Thiếu cân", "badge-low"];
    if (bmi < 23) return ["Bình thường", "badge-good"];
    if (bmi < 25) return ["Thừa cân", "badge-ok"];
    return ["Béo phì", "badge-limit"];
  }

  function calculate() {
    const v = Object.fromEntries(new FormData(form));
    const age = Number(v.age), height = Number(v.height), weight = Number(v.weight);
    const activity = Number(v.activity), goal = Number(v.goal);
    if (!(age >= 15 && age <= 90) || !(height >= 120 && height <= 230) || !(weight >= 30 && weight <= 250)) {
      errorBox.textContent = "Vui lòng nhập tuổi 15–90, chiều cao 120–230 cm và cân nặng 30–250 kg.";
      errorBox.hidden = false;
      return;
    }
    errorBox.hidden = true;
    store.set(PROFILE_KEY, v);

    const bmr = 10 * weight + 6.25 * height - 5 * age + (v.sex === "male" ? 5 : -161);
    const tdee = bmr * activity;
    // Không đề xuất mức calo thấp hơn BMR (hoặc 1.200 kcal)
    const target = Math.max(Math.round(tdee + goal), Math.round(Math.max(bmr, 1200)));
    const bmi = weight / (height / 100) ** 2;

    // Protein theo cân nặng, chất béo 25–30% năng lượng, phần còn lại là carb
    const proteinPerKg = goal < 0 ? 1.6 : goal > 0 ? 1.8 : 1.2;
    const protein = Math.round(weight * proteinPerKg);
    const fat = Math.round((target * (goal < 0 ? 0.25 : 0.3)) / 9);
    const carb = Math.max(0, Math.round((target - protein * 4 - fat * 9) / 4));

    out("bmr").textContent = fmt.num(Math.round(bmr));
    out("tdee").textContent = fmt.num(Math.round(tdee));
    out("target").textContent = fmt.num(target);

    out("bmi").textContent = fmt.num(bmi, 1);
    const [label, cls] = bmiCategory(bmi);
    const badge = out("bmi-label");
    badge.textContent = label;
    badge.className = "badge " + cls;
    const pos = Math.min(100, Math.max(0, ((bmi - 15) / 20) * 100));
    document.querySelector("[data-bmi-pin]").style.left = pos + "%";
    const lo = 18.5 * (height / 100) ** 2, hi = 22.9 * (height / 100) ** 2;
    out("ideal").textContent = `Cân nặng hợp lý với chiều cao ${height} cm: khoảng ${fmt.num(lo, 1)} – ${fmt.num(hi, 1)} kg.`;

    const kcal = { protein: protein * 4, carb: carb * 4, fat: fat * 9 };
    const total = kcal.protein + kcal.carb + kcal.fat || 1;
    [["protein", protein], ["carb", carb], ["fat", fat]].forEach(([k, g]) => {
      out(k).textContent = `${fmt.num(g)} g · ${Math.round((kcal[k] / total) * 100)}%`;
      document.querySelector(`[data-bar="${k}"]`).style.width = (kcal[k] / total) * 100 + "%";
    });
    out("water").textContent = `${fmt.num((weight * 0.035), 1)} lít`;

    latest = { calories: target, protein, carb, fat };
    saveBtn.disabled = false;
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); calculate(); });
  form.addEventListener("change", calculate);
  saveBtn.addEventListener("click", async () => {
    if (!latest) return;
    const body = Object.fromEntries(new FormData(form));
    saveBtn.disabled = true;
    try {
      await diary.setTarget(latest, body);
      toast(`Đã lưu mục tiêu ${fmt.num(latest.calories)} kcal mỗi ngày${diary.mode === "server" ? " vào tài khoản" : ""}.`);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      saveBtn.disabled = false;
    }
  });
  calculate();
})();
