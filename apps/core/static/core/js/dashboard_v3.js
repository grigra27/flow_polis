"use strict";
(() => {
  const form = document.getElementById("dashboard-filters");
  const today = document.getElementById("dashboard-today");
  if (form && today) {
    today.addEventListener("click", () => {
      document.getElementById("dashboard-date").value = today.dataset.today;
      form.requestSubmit();
    });
  }
})();
