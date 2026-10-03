/**
 * Voucher keyboard layer (Sale, Purchase, Sale/Purchase Return, Payment,
 * Receipt, Credit/Debit Note, Journal).
 *
 * Works like desktop ERP software:
 *   Enter            go to the next field (Shift+Enter = previous)
 *   dropdown fields  open a search box: type to filter, Up/Down to move,
 *                    Enter to pick and jump to the next field, Esc to close
 *   On a closed dropdown: Enter = keep value & move on, or just start typing
 *   Item line        after picking an item, Unit lists only that item's
 *                    units (1 unit = skipped automatically)
 *   Enter on a blank item line ends the items and jumps to Bill Sundries / Save
 *   Enter on the last field of the last item line adds a new line
 *
 * Purely front end. It only talks to the existing item-detail URL.
 * Sale/Purchase screens (no data-voucher-kind) use the navigation below;
 * Payment/Receipt/Note/Journal keep their own Enter logic in cash_voucher.js,
 * this file only adds the searchable dropdowns to them.
 */
(function () {
    'use strict';

    var wrap = document.querySelector('.sale-voucher-wrapper');
    if (!wrap) { return; }

    var isCashFamily = wrap.hasAttribute('data-voucher-kind');
    var coarse = !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);

    var bypass = false;          // true while we replay an Enter for cash_voucher.js
    var suppressOpen = false;    // true while we put focus back without re-opening the list
    var lastKeyAt = 0;           // last Enter/Tab keydown time (to tell keyboard focus from mouse focus)
    var lastDir = 1;

    function jq() { return window.jQuery || (window.django && window.django.jQuery) || null; }
    function esc(v) {
        return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function isVisible(el) {
        return !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
    }

    /* =====================================================================
       1. Searchable dropdown
       ===================================================================== */
    function isEnhanced(el) {
        return !!el && el.tagName === 'SELECT' && !el.multiple && !el.disabled &&
            wrap.contains(el) && !el.classList.contains('select2-hidden-accessible') &&
            !el.closest('.item-info-panel') && !el.closest('.view-mode-toggle');
    }

    function realOptionCount(sel) {
        var n = 0;
        for (var i = 0; i < sel.options.length; i++) { if (sel.options[i].value !== '') { n++; } }
        return n;
    }

    var pop = null;
    var st = null;

    function filterOptions(opts, query) {
        var q = query.trim().toLowerCase();
        if (!q) { return opts.slice(); }
        var tokens = q.split(/\s+/);
        var out = [];
        opts.forEach(function (o) {
            if (o.value === '') { return; }
            var t = o.text.toLowerCase();
            for (var i = 0; i < tokens.length; i++) { if (t.indexOf(tokens[i]) === -1) { return; } }
            var rank = 2;
            if (t.indexOf(tokens[0]) === 0) { rank = 0; }
            else if ((' ' + t).indexOf(' ' + tokens[0]) !== -1) { rank = 1; }
            out.push({ o: o, rank: rank });
        });
        out.sort(function (a, b) { return a.rank - b.rank || a.o.i - b.o.i; });
        return out.map(function (x) { return x.o; });
    }

    function renderPop(initial) {
        var all = filterOptions(st.opts, st.search.value);
        var LIMIT = 300;
        st.filtered = all.slice(0, LIMIT);
        if (initial) {
            var cur = st.sel.value, idx = 0;
            for (var k = 0; k < st.filtered.length; k++) {
                if (st.filtered[k].value === cur) { idx = k; break; }
            }
            st.hi = idx;
        } else {
            st.hi = 0;
        }
        var html = '';
        st.filtered.forEach(function (o, i) {
            var label = o.value === '' ? '\u2014 none \u2014' : esc(o.text);
            html += '<div class="kbc-opt' + (o.value === st.sel.value ? ' kbc-sel' : '') +
                (i === st.hi ? ' kbc-hi' : '') + (o.value === '' ? ' kbc-none' : '') +
                '" data-i="' + i + '" role="option">' + label + '</div>';
        });
        if (!st.filtered.length) { html = '<div class="kbc-empty">No match</div>'; }
        st.list.innerHTML = html;
        st.foot.textContent = all.length > LIMIT
            ? (all.length - LIMIT) + ' more \u2014 keep typing to narrow'
            : '\u2191\u2193 move \u00b7 Enter select \u00b7 Esc close';
        scrollToHi();
    }

    function scrollToHi() {
        var el = st.list.querySelector('.kbc-hi');
        if (el && el.scrollIntoView) { el.scrollIntoView({ block: 'nearest' }); }
    }

    function setHi(i) {
        if (!st.filtered.length) { return; }
        i = Math.max(0, Math.min(st.filtered.length - 1, i));
        var old = st.list.querySelector('.kbc-hi');
        if (old) { old.classList.remove('kbc-hi'); }
        st.hi = i;
        var nu = st.list.querySelector('[data-i="' + i + '"]');
        if (nu) { nu.classList.add('kbc-hi'); }
        scrollToHi();
    }

    function positionPop() {
        if (!pop || !st) { return; }
        var r = st.sel.getBoundingClientRect();
        var w = Math.max(r.width, 280);
        var left = Math.max(4, Math.min(r.left, window.innerWidth - w - 4));
        pop.style.width = w + 'px';
        pop.style.left = left + 'px';
        var below = window.innerHeight - r.bottom;
        if (below < 300 && r.top > below) {
            pop.style.top = 'auto';
            pop.style.bottom = (window.innerHeight - r.top + 2) + 'px';
        } else {
            pop.style.bottom = 'auto';
            pop.style.top = (r.bottom + 2) + 'px';
        }
    }

    function closePop(refocus) {
        if (!pop) { return; }
        var sel = st && st.sel;
        if (pop.parentNode) { pop.parentNode.removeChild(pop); }
        pop = null;
        st = null;
        if (refocus && sel) { focusNoOpen(sel); }
    }

    function focusNoOpen(el) {
        suppressOpen = true;
        try { el.focus(); } finally { suppressOpen = false; }
    }

    function openPop(sel, seed) {
        closePop(false);
        var opts = Array.prototype.map.call(sel.options, function (o, i) {
            return { i: i, value: o.value, text: (o.text || '').trim(), disabled: o.disabled };
        }).filter(function (o) { return !o.disabled; });

        pop = document.createElement('div');
        pop.className = 'kbc-pop';
        pop.innerHTML = '<input type="text" class="kbc-search" autocomplete="off" spellcheck="false" ' +
            'placeholder="Type to search\u2026"><div class="kbc-list" role="listbox"></div><div class="kbc-foot"></div>';
        document.body.appendChild(pop);
        st = {
            sel: sel, opts: opts, filtered: [], hi: 0,
            search: pop.querySelector('.kbc-search'),
            list: pop.querySelector('.kbc-list'),
            foot: pop.querySelector('.kbc-foot')
        };
        st.search.value = seed || '';
        positionPop();
        renderPop(!seed);

        st.search.addEventListener('input', function () { renderPop(false); });
        st.search.addEventListener('keydown', onSearchKey);
        st.search.addEventListener('blur', function () {
            setTimeout(function () {
                if (pop && st && document.activeElement !== st.search) { closePop(false); }
            }, 0);
        });
        st.list.addEventListener('mousedown', function (e) {
            e.preventDefault();
            var t = e.target.closest ? e.target.closest('.kbc-opt') : null;
            if (t) { pick(parseInt(t.getAttribute('data-i'), 10), 1); }
        });
        st.search.focus();
        try { st.search.setSelectionRange(st.search.value.length, st.search.value.length); } catch (e) { /* ignore */ }
    }

    function onSearchKey(e) {
        if (!st) { return; }
        var k = e.key;
        if (k === 'ArrowDown') { e.preventDefault(); setHi(st.hi + 1); }
        else if (k === 'ArrowUp') { e.preventDefault(); setHi(st.hi - 1); }
        else if (k === 'PageDown') { e.preventDefault(); setHi(st.hi + 8); }
        else if (k === 'PageUp') { e.preventDefault(); setHi(st.hi - 8); }
        else if (k === 'Enter') { e.preventDefault(); e.stopPropagation(); pick(st.hi, 1); }
        else if (k === 'Tab') {
            e.preventDefault();
            if (st.filtered.length) { pick(st.hi, e.shiftKey ? -1 : 1); }
            else { var s = st.sel; closePop(false); focusNoOpen(s); moveFrom(s, e.shiftKey ? -1 : 1); }
        }
        else if (k === 'Escape') { e.preventDefault(); e.stopPropagation(); closePop(true); }
    }

    function pick(index, dir) {
        if (!st) { return; }
        var o = st.filtered[index];
        if (!o) { return; }
        var sel = st.sel;
        var changed = sel.value !== o.value;
        closePop(false);
        if (changed) {
            sel.value = o.value;
            sel.dispatchEvent(new Event('change', { bubbles: true }));
        }
        focusNoOpen(sel);
        var after = function () { moveFrom(sel, dir); };
        if (changed && /-item$/.test(sel.name || '')) {
            var row = sel.closest('.item-form-row');
            if (row) { restrictUnits(row, sel.value, false).then(after, after); return; }
        }
        after();
    }

    window.addEventListener('resize', positionPop);
    document.addEventListener('scroll', function (e) {
        if (pop && !pop.contains(e.target)) { positionPop(); }
    }, true);
    window.addEventListener('pagehide', function () { closePop(false); });

    /* =====================================================================
       2. Per-item Unit list
       ===================================================================== */
    var itemCache = {};

    function itemInfo(id) {
        if (!itemCache[id]) {
            var prefix = window.location.pathname.split('/masters/')[0];
            itemCache[id] = fetch(prefix + '/masters/item-detail/' + id + '/', {
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            }).then(function (r) { return r.json(); }).catch(function () {
                delete itemCache[id];
                return null;
            });
        }
        return itemCache[id];
    }

    function rebuildSelect(sel, list, want) {
        sel.innerHTML = '';
        list.forEach(function (u) {
            var o = document.createElement('option');
            o.value = u.v;
            o.textContent = u.t;
            sel.appendChild(o);
        });
        var found = false;
        for (var i = 0; i < sel.options.length; i++) {
            if (want != null && sel.options[i].value === String(want)) { sel.selectedIndex = i; found = true; break; }
        }
        if (!found && sel.options.length) { sel.selectedIndex = 0; }
    }

    // keepCurrent = true for lines that were already saved: their saved unit
    // is always kept in the list even if it is no longer one of the item's units.
    function restrictUnits(row, itemId, keepCurrent) {
        var sel = row.querySelector('select[name$="-unit"]');
        if (!sel) { return Promise.resolve(); }
        if (!sel._kbAll) {
            sel._kbAll = Array.prototype.map.call(sel.options, function (o) { return { v: o.value, t: o.text }; });
        }
        var current = sel.value;
        if (!itemId || isNaN(itemId)) {
            rebuildSelect(sel, sel._kbAll, current);
            return Promise.resolve();
        }
        return itemInfo(itemId).then(function (data) {
            if (!data || !data.success || !data.units || !data.units.length) {
                rebuildSelect(sel, sel._kbAll, current);
                return;
            }
            var list = data.units.map(function (u) { return { v: String(u.id), t: u.name }; });
            var want = list[0].v;
            if (keepCurrent && current) {
                want = current;
                var present = list.some(function (u) { return u.v === current; });
                if (!present) {
                    var saved = sel._kbAll.filter(function (u) { return u.v === current; })[0];
                    if (saved) { list.push(saved); }
                }
            }
            rebuildSelect(sel, list, want);
        });
    }

    // Item changed any way at all (our list, touch pickers, other scripts)
    document.addEventListener('change', function (e) {
        var t = e.target;
        if (t && t.tagName === 'SELECT' && /-item$/.test(t.name || '')) {
            var row = t.closest('.item-form-row');
            if (row) { restrictUnits(row, t.value, false); }
        }
    }, true);

    function restrictAllSavedRows() {
        var rows = wrap.querySelectorAll('.item-form-row');
        Array.prototype.forEach.call(rows, function (row) {
            var it = row.querySelector('select[name$="-item"]');
            if (it && it.value) { restrictUnits(row, it.value, true); }
        });
    }

    /* =====================================================================
       3. Moving between fields
       ===================================================================== */
    function jqSelect2Open(select) {
        var $ = jq();
        if ($ && select) { try { $(select).select2('open'); } catch (e) { /* ignore */ } }
    }
    function select2Source(selection) {
        var c = selection.closest('.select2-container');
        return c ? c.previousElementSibling : null;
    }

    function focusEl(el) {
        if (!el) { return; }
        el.focus();
        var t = (el.type || '').toLowerCase();
        if (el.tagName === 'INPUT' && (t === 'text' || t === 'number' || t === 'search' || t === 'tel' || t === 'email' || t === 'url' || t === 'date' || t === '')) {
            try { el.select(); } catch (e) { /* ignore */ }
        }
    }

    var FIELD_SEL = [
        '.voucher-header-card select', '.voucher-header-card input', '.voucher-header-card textarea',
        '.voucher-header-card .select2-selection',
        '#busy-items-tbody select', '#busy-items-tbody input',
        '#busy-sundries-tbody select', '#busy-sundries-tbody input',
        '.voucher-action-bar button[name="_save"]'
    ].join(',');

    function saleFields() {
        return Array.prototype.filter.call(wrap.querySelectorAll(FIELD_SEL), function (e) {
            if (e.disabled || e.readOnly) { return false; }
            if (e.classList.contains('select2-hidden-accessible') || e.classList.contains('select2-search__field')) { return false; }
            if (e.closest('.item-info-panel')) { return false; }
            var t = (e.type || '').toLowerCase();
            if (t === 'hidden') { return false; }
            if (t === 'checkbox' && !e.closest('.voucher-header-card')) { return false; }
            return isVisible(e);
        });
    }

    function visibleRows(selector) {
        return Array.prototype.filter.call(wrap.querySelectorAll(selector), isVisible);
    }

    function focusAfterItems() {
        var list = saleFields();
        for (var i = 0; i < list.length; i++) {
            if (list[i].closest('#busy-sundries-tbody') || list[i].matches('button[name="_save"]')) {
                focusEl(list[i]);
                return;
            }
        }
    }

    function saleNav(el, dir) {
        var list = saleFields();
        var i = list.indexOf(el);
        if (i < 0) { return; }

        var row = el.closest('#busy-items-tbody .item-form-row');
        if (dir > 0 && row) {
            var itemSel = row.querySelector('select[name$="-item"]');
            var rows = visibleRows('#busy-items-tbody .item-form-row');
            var blank = !itemSel || !itemSel.value;

            // Enter on a blank item = "no more items"
            if (el === itemSel && blank) {
                var isSaved = !!row.querySelector('input[type="checkbox"][name$="-DELETE"]');
                if (rows.indexOf(row) > 0 && !isSaved) {
                    var del = row.querySelector('.btn-delete-item-row');
                    if (del) { del.click(); }
                }
                focusAfterItems();
                return;
            }
            // Enter on the last field of the last line adds a new line
            var rowFields = list.filter(function (f) { return row.contains(f); });
            var lastCell = rowFields[rowFields.length - 1] === el;
            if (lastCell && rows[rows.length - 1] === row && !blank) {
                var add = document.getElementById('btn-add-item-row');
                if (add) { add.click(); return; }
            }
        }
        var nxt = list[i + dir];
        if (nxt) {
            if (nxt.classList && nxt.classList.contains('select2-selection')) {
                nxt.focus();
            } else {
                focusEl(nxt);
            }
        }
    }

    function moveFrom(el, dir) {
        dir = dir || 1;
        lastDir = dir;
        lastKeyAt = Date.now();   // always a keyboard-driven move (also after a slow unit lookup)
        if (isCashFamily) {
            // let cash_voucher.js apply its own rules (empty account, journal Dr/Cr, new line...)
            bypass = true;
            try {
                el.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'Enter', shiftKey: dir < 0, bubbles: true, cancelable: true
                }));
            } finally { bypass = false; }
            return;
        }
        saleNav(el, dir);
    }

    /* =====================================================================
       4. Event wiring (capture phase so we run before the older handlers)
       ===================================================================== */
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === 'Tab') {
            lastKeyAt = Date.now();
            lastDir = e.shiftKey ? -1 : 1;
        }
        if (bypass || e.isComposing) { return; }
        var t = e.target;
        if (!t || !wrap.contains(t)) { return; }

        // ---- dropdowns (all vouchers) ----
        if (isEnhanced(t)) {
            var k = e.key;
            if (k === 'Enter') {
                e.preventDefault(); e.stopImmediatePropagation();
                if (t.value) { moveFrom(t, e.shiftKey ? -1 : 1); }
                else { openPop(t, ''); }
                return;
            }
            if (k === 'ArrowDown' || k === 'ArrowUp' || k === 'F4' || k === ' ') {
                e.preventDefault(); e.stopImmediatePropagation();
                openPop(t, '');
                return;
            }
            if (k.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
                e.preventDefault(); e.stopImmediatePropagation();
                openPop(t, k);
                return;
            }
            return;
        }

        if (isCashFamily || e.key !== 'Enter') { return; }

        // ---- Sale / Purchase / Returns: Enter on non-dropdown fields ----
        var inForm = t.closest('.voucher-header-card, #busy-items-tbody, #busy-sundries-tbody');
        if (!inForm) { return; }
        if (t.classList && t.classList.contains('select2-selection')) {
            e.preventDefault(); e.stopImmediatePropagation();
            var src = select2Source(t);
            if (src && src.value) { saleNav(t, e.shiftKey ? -1 : 1); }
            else { jqSelect2Open(src); }
            return;
        }
        if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') {
            e.preventDefault(); e.stopImmediatePropagation();
            saleNav(t, e.shiftKey ? -1 : 1);
        }
    }, true);

    // Mouse: open our search list instead of the browser's plain one
    document.addEventListener('mousedown', function (e) {
        if (coarse) { return; }
        var t = e.target;
        if (t && t.tagName === 'SELECT' && isEnhanced(t)) {
            e.preventDefault();
            focusNoOpen(t);
            openPop(t, '');
        }
    }, true);

    // Keyboard arrival (Enter / Tab from the previous field) opens the list
    document.addEventListener('focusin', function (e) {
        if (suppressOpen) { return; }
        var t = e.target;
        if (!t || Date.now() - lastKeyAt > 250) { return; }

        if (isEnhanced(t)) {
            var name = t.name || '';
            // A unit with a single choice is not worth stopping at
            if (/-unit$/.test(name) && realOptionCount(t) <= 1) {
                moveFrom(t, lastDir);
                return;
            }
            if (!t.value || /(^|-)(item|account|bill_sundry)$/.test(name)) { openPop(t, ''); }
            return;
        }
        if (t.classList && t.classList.contains('select2-selection') && !isCashFamily) {
            var src = select2Source(t);
            if (src && !src.value) { jqSelect2Open(src); }
        }
    });

    // Returns: after choosing in the "Against ... Invoice" search, move on
    (function bindSelect2Advance() {
        var $ = jq();
        if (!$ || isCashFamily) { return; }
        $(document).on('select2:select', '.voucher-header-card select', function () {
            var sel = this;
            setTimeout(function () {
                var c = sel.nextElementSibling;
                var selection = c && c.querySelector ? c.querySelector('.select2-selection') : null;
                if (selection) { saleNav(selection, 1); }
            }, 0);
        });
    })();

    /* =====================================================================
       5. Start-up
       ===================================================================== */
    restrictAllSavedRows();

    // Add (new) voucher on a desktop: start on the date, like the cash vouchers do
    var narrow = !!(window.matchMedia && window.matchMedia('(max-width: 768px)').matches) || wrap.classList.contains('force-mobile');
    if (!isCashFamily && !narrow && !coarse) {
        var hasSaved = !!wrap.querySelector('#busy-items-tbody input[type="checkbox"][name$="-DELETE"]');
        var hasErrors = !!document.querySelector('.field-error, .errorlist');
        var dateEl = document.getElementById('id_date');
        if (!hasSaved && !hasErrors && dateEl && isVisible(dateEl)) { focusEl(dateEl); }
    }
})();
