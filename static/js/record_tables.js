(() => {
    'use strict';

    const tables = [...document.querySelectorAll('table.record-table')];
    if (!tables.length) return;

    const texts = [];
    document.querySelectorAll('[data-expandable-text]').forEach((root, index) => {
        const content = root.querySelector('.record-text-content');
        const button = root.querySelector('.record-text-toggle');
        if (!content || !button) return;
        content.id = `record-text-${index}`;
        button.setAttribute('aria-controls', content.id);
        root.classList.add('is-collapsible');
        const label = root.dataset.expandableText;
        const setExpanded = (expanded) => {
            root.classList.toggle('is-expanded', expanded);
            button.setAttribute('aria-expanded', String(expanded));
            button.textContent = expanded ? 'Свернуть' : 'Ещё';
            button.setAttribute('aria-label', `${expanded ? 'Свернуть' : 'Показать полностью'}: ${label}`);
        };
        setExpanded(false);
        button.addEventListener('click', (event) => {
            event.stopPropagation();
            setExpanded(button.getAttribute('aria-expanded') !== 'true');
            schedule();
        });
        texts.push({content, button, setExpanded});
    });

    const heads = tables.filter((table) => table.tHead && table.tBodies[0]?.rows.length).map((table) => {
        const viewport = table.parentElement;
        viewport.classList.add('record-table-viewport');
        const floating = document.createElement('div');
        floating.className = 'record-table-floating-head';
        floating.hidden = true;
        floating.setAttribute('aria-hidden', 'true');
        floating.setAttribute('inert', '');
        const copy = document.createElement('table');
        copy.className = table.className;
        const columns = document.createElement('colgroup');
        for (const cell of table.tHead.rows[0].cells) {
            columns.appendChild(document.createElement('col'));
        }
        copy.append(columns, table.tHead.cloneNode(true));
        copy.querySelectorAll('[id]').forEach((node) => node.removeAttribute('id'));
        floating.appendChild(copy);
        viewport.appendChild(floating);
        viewport.addEventListener('scroll', schedule, {passive: true});
        return {table, viewport, floating, copy, columns};
    });

    function topOffset() {
        let bottom = 0;
        for (const nav of document.querySelectorAll('.app-navbar-sticky, .ecosystem-strip')) {
            const rect = nav.getBoundingClientRect();
            if (rect.height && rect.top <= bottom + 1) bottom = Math.max(bottom, rect.bottom);
        }
        return bottom;
    }

    function syncHeads() {
        const top = topOffset();
        heads.forEach(({table, viewport, floating, copy, columns}) => {
            const bounds = table.getBoundingClientRect();
            const header = table.tHead.getBoundingClientRect();
            const clip = viewport.getBoundingClientRect();
            const canScroll = viewport.scrollWidth > viewport.clientWidth + 1;
            if (canScroll) {
                viewport.tabIndex = 0;
                viewport.setAttribute('role', 'region');
                viewport.setAttribute('aria-label', 'Прокрутка таблицы по горизонтали');
            } else {
                viewport.removeAttribute('tabindex');
                viewport.removeAttribute('role');
                viewport.removeAttribute('aria-label');
            }
            const left = Math.max(clip.left, 0);
            const right = Math.min(clip.right, document.documentElement.clientWidth);
            const visible = window.innerWidth >= 992 && right > left && header.top < top && bounds.bottom > top + header.height;
            floating.hidden = !visible;
            if (!visible) return;
            floating.style.top = `${top}px`;
            floating.style.left = `${left}px`;
            floating.style.width = `${right - left}px`;
            copy.style.width = `${bounds.width}px`;
            copy.style.transform = `translateX(${bounds.left - left}px)`;
            [...table.tHead.rows[0].cells].forEach((cell, index) => {
                columns.children[index].style.width = `${cell.getBoundingClientRect().width}px`;
            });
        });
    }

    function syncTexts() {
        texts.forEach(({content, button, setExpanded}) => {
            const lineHeight = parseFloat(getComputedStyle(content).lineHeight);
            const truncated = content.scrollHeight > lineHeight * 2 + 1;
            button.hidden = !truncated;
            if (!truncated) setExpanded(false);
        });
    }

    let frame = null;
    let measureText = true;
    function schedule(remeasure = false) {
        measureText ||= remeasure === true;
        if (frame !== null) return;
        frame = requestAnimationFrame(() => {
            frame = null;
            if (measureText) syncTexts();
            measureText = false;
            syncHeads();
        });
    }

    window.addEventListener('scroll', () => schedule(), {passive: true});
    window.addEventListener('resize', () => schedule(true));
    window.addEventListener('load', () => schedule(true));
    if (window.ResizeObserver) {
        const observer = new ResizeObserver(() => schedule(true));
        tables.forEach((table) => observer.observe(table));
        document.querySelectorAll('.app-navbar-sticky, .ecosystem-strip').forEach((nav) => observer.observe(nav));
    }
    document.fonts?.ready.then(() => schedule(true));
    schedule(true);
})();
