(() => {
    const select = document.getElementById("template-policy");
    if (!select) return;
    const preview = document.getElementById("sample-preview");
    const confirm = select.form.elements.confirm_template;
    async function update() {
        const id = select.value;
        confirm.checked = false;
        confirm.disabled = true;
        confirm.required = Boolean(id);
        preview.textContent = id ? "Загружаем условия полиса…" : "";
        if (!id) return;
        const url = new URL(window.location.href);
        url.searchParams.set("sample", id);
        try {
            const response = await fetch(url, {credentials: "same-origin"});
            if (!response.ok) throw new Error();
            const html = await response.text();
            if (select.value === id) {
                preview.innerHTML = html;
                confirm.disabled = false;
            }
        } catch {
            if (select.value === id) preview.textContent = "Не удалось загрузить образец. Выберите полис повторно.";
        }
    }
    select.addEventListener("change", update);
    update();
})();
