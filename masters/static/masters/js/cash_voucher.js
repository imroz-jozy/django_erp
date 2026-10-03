/**
 * Payment / Receipt / Journal voucher front end.
 * Same behaviour as the Sale voucher screen: keyboard-first grid,
 * Auto/Desktop/Mobile layout toggle, live totals.
 *
 *   Enter            next field        Shift+Enter   previous field
 *   F2               save              Ctrl+Delete   remove current line
 *   Enter on last filled line -> adds a new line
 *   Enter on an empty account line -> jumps to Save
 *
 * Journal extras: picking an account auto-fills the balancing Dr/Cr,
 * typing in Debit clears Credit (and vice-versa), live balance badge.
 */
(function () {
    'use strict';

    function init($) {
        var $wrap = $('.sale-voucher-wrapper[data-voucher-kind]');
        if (!$wrap.length) { return; }
        var isJournal = $wrap.attr('data-voucher-kind') === 'journal';
        var $form = $('#voucher_form');
        var $tbody = $('#voucher-lines-tbody');
        var $total = $('input[name$="-TOTAL_FORMS"]').first();
        var prefix = ($total.attr('name') || 'lines-TOTAL_FORMS').replace(/-TOTAL_FORMS$/, '');

        /* ---------- Auto / Desktop / Mobile layout ---------- */
        function applyLayoutClass() {
            var mobile;
            if ($wrap.hasClass('force-desktop')) { mobile = false; }
            else if ($wrap.hasClass('force-mobile')) { mobile = true; }
            else { mobile = window.matchMedia('(max-width: 768px)').matches; }
            $wrap.toggleClass('is-mobile-layout', mobile);
        }

        window.setVoucherMode = function (mode) {
            $wrap.removeClass('auto-responsive force-desktop force-mobile');
            $('.view-mode-btn').removeClass('active');
            if (mode === 'desktop') { $wrap.addClass('force-desktop'); $('#btn-mode-desktop').addClass('active'); }
            else if (mode === 'mobile') { $wrap.addClass('force-mobile'); $('#btn-mode-mobile').addClass('active'); }
            else { mode = 'auto'; $wrap.addClass('auto-responsive'); $('#btn-mode-auto').addClass('active'); }
            applyLayoutClass();
            try { window.localStorage.setItem('voucherViewMode', mode); } catch (e) { /* ignore */ }
        };

        var savedMode = 'auto';
        try { savedMode = window.localStorage.getItem('voucherViewMode') || 'auto'; } catch (e) { /* ignore */ }
        window.setVoucherMode(savedMode);
        $(window).on('resize orientationchange', applyLayoutClass);

        /* ---------- helpers ---------- */
        function round2(v) { return Math.round(((parseFloat(v) || 0) + Number.EPSILON) * 100) / 100; }
        function fmtMoney(v) {
            var n = round2(v);
            return (n < 0 ? '- ₹ ' : '₹ ') + Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        function num($el) { return parseFloat($el.val()) || 0; }
        function liveRows() { return $tbody.children('.voucher-line-row').filter(function () { return $(this).css('display') !== 'none'; }); }
        function isSavedRow($row) { return $row.find('input[type="checkbox"][name$="-DELETE"]').length > 0; }

        // Unsaved rows render a 0 default for debit/credit; show them blank
        // instead (put back to 0 on submit - the model needs a number).
        function blankZeros($scope) {
            if (!isJournal) { return; }
            $scope.find('input[name$="-debit"], input[name$="-credit"]').each(function () {
                var $row = $(this).closest('.voucher-line-row');
                if (!isSavedRow($row) && !(parseFloat($(this).val()) > 0)) { $(this).val(''); }
            });
        }

        function renumber() {
            liveRows().each(function (i) { $(this).find('.row-num').text(i + 1); });
        }

        /* ---------- totals ---------- */
        function updateTotals() {
            if (isJournal) {
                var dr = 0, cr = 0;
                liveRows().each(function () {
                    dr += num($(this).find('input[name$="-debit"]'));
                    cr += num($(this).find('input[name$="-credit"]'));
                });
                dr = round2(dr); cr = round2(cr);
                var diff = round2(dr - cr);
                var balanced = Math.abs(diff) < 0.005 && dr > 0;
                var unbalanced = Math.abs(diff) >= 0.005;
                $('#v-sum-debit').text(fmtMoney(dr));
                $('#v-sum-credit').text(fmtMoney(cr));
                $('.v-sum-diff').text(fmtMoney(Math.abs(diff)));
                $('#v-diff-row').toggleClass('is-balanced', balanced).toggleClass('is-unbalanced', unbalanced);
                $('#v-balance-badge')
                    .toggleClass('is-balanced', balanced)
                    .toggleClass('is-unbalanced', unbalanced)
                    .text(balanced ? '✓ BALANCED' : (unbalanced ? ('⚠ OUT OF BALANCE — ' + (diff > 0 ? 'Cr' : 'Dr') + ' short') : '—'));
                $('#v-balance-note').text(unbalanced ? 'Debit and Credit must be equal or the voucher will not save.' : '');
            } else {
                var sum = 0, count = 0;
                liveRows().each(function () {
                    var a = num($(this).find('input[name$="-amount"]'));
                    sum += a;
                    if (a > 0) { count++; }
                });
                $('#v-sum-lines').text(count);
                $('.v-sum-total').text(fmtMoney(sum));
            }
        }

        /* ---------- row add / delete ---------- */
        function addRow() {
            var tpl = $('#line-empty-form-template').text();
            if (!tpl || !tpl.trim()) { alert('Line template not found. Please refresh the page.'); return null; }
            var n = parseInt($total.val(), 10) || 0;
            var $row = $(tpl.replace(/__prefix__/g, n));
            $tbody.append($row);
            $total.val(n + 1);
            blankZeros($row);
            renumber();
            $row.find('select, input').filter(':visible').first().focus();
            updateTotals();
            return $row;
        }

        // Re-sequence unsaved rows after one is removed so the formset has no
        // index gaps (saved rows keep their index and are only flagged DELETE).
        function reindexNewRows() {
            var initial = parseInt($total.data('initial-count'), 10);
            if (isNaN(initial)) {
                initial = 0;
                $tbody.children('.voucher-line-row').each(function () { if (isSavedRow($(this))) { initial++; } });
                $total.data('initial-count', initial);
            }
            var idx = initial;
            var re = new RegExp(prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '-\\d+-');
            $tbody.children('.voucher-line-row').each(function () {
                var $row = $(this);
                if (isSavedRow($row)) { return; }
                var np = prefix + '-' + idx + '-';
                $row.find('[name]').each(function () {
                    var nm = $(this).attr('name');
                    if (nm && re.test(nm)) { $(this).attr('name', nm.replace(re, np)); }
                });
                $row.find('[id]').each(function () {
                    var id = $(this).attr('id');
                    if (id && id.indexOf('id_' + prefix + '-') === 0) { $(this).attr('id', id.replace(re, np)); }
                });
                idx++;
            });
            $total.val(idx);
        }

        function removeRow($row) {
            var $del = $row.find('input[type="checkbox"][name$="-DELETE"]');
            if ($del.length) {
                $del.prop('checked', true);
                $row.hide();
            } else {
                $row.remove();
                reindexNewRows();
            }
            renumber();
            updateTotals();
        }

        $(document).on('click', '#btn-add-line', function (e) { e.preventDefault(); addRow(); });
        $(document).on('click', '.btn-delete-line-row', function (e) {
            e.preventDefault();
            removeRow($(this).closest('.voucher-line-row'));
        });

        /* ---------- journal: Dr/Cr exclusivity + auto balance ---------- */
        function otherTotals($exceptRow) {
            var dr = 0, cr = 0;
            liveRows().each(function () {
                if ($exceptRow && this === $exceptRow[0]) { return; }
                dr += num($(this).find('input[name$="-debit"]'));
                cr += num($(this).find('input[name$="-credit"]'));
            });
            return round2(dr - cr);
        }

        if (isJournal) {
            $(document).on('input', '.voucher-line-row input[name$="-debit"]', function () {
                if (num($(this)) > 0) { $(this).closest('.voucher-line-row').find('input[name$="-credit"]').val(''); }
            });
            $(document).on('input', '.voucher-line-row input[name$="-credit"]', function () {
                if (num($(this)) > 0) { $(this).closest('.voucher-line-row').find('input[name$="-debit"]').val(''); }
            });
            // Choosing an account on an empty line pre-fills the balancing side.
            $(document).on('change', '.voucher-line-row select[name$="-account"]', function () {
                var $row = $(this).closest('.voucher-line-row');
                var $dr = $row.find('input[name$="-debit"]');
                var $cr = $row.find('input[name$="-credit"]');
                if (!$(this).val() || num($dr) > 0 || num($cr) > 0) { return; }
                var diff = otherTotals($row);
                if (diff > 0.004) { $cr.val(diff.toFixed(2)); }
                else if (diff < -0.004) { $dr.val((-diff).toFixed(2)); }
                updateTotals();
            });
        }

        $(document).on('input change keyup', '.voucher-line-row input, .voucher-line-row select', updateTotals);

        /* ---------- keyboard navigation ---------- */
        // select2 (used for "Against Invoice") hides the real <select> and shows
        // a focusable .select2-selection instead - navigate via that.
        function fields() {
            return $wrap.find('.voucher-header-card, .busy-table')
                .find('input, select, textarea, .select2-selection')
                .filter(function () {
                    var t = (this.type || '').toLowerCase();
                    if ($(this).hasClass('select2-hidden-accessible')) { return false; }
                    if ($(this).hasClass('select2-search__field')) { return false; }
                    return !this.disabled && !this.readOnly && t !== 'hidden' && t !== 'checkbox' && $(this).is(':visible');
                });
        }
        function focusEl($el) {
            if (!$el || !$el.length) { return; }
            $el.focus();
            if ($el.is('input')) { try { $el.select(); } catch (e) { /* ignore */ } }
            if ($el.hasClass('select2-selection')) {   // open the search box right away
                var $sel = $el.closest('.select2-container').prev('select');
                try { $sel.select2('open'); } catch (e) { /* ignore */ }
            }
        }
        // After choosing a value in a header select2, continue to the next field.
        $(document).on('select2:select', '.voucher-header-card select', function () {
            var $sel = $(this);
            setTimeout(function () {
                var $all = fields();
                var $me = $sel.next('.select2-container').find('.select2-selection');
                var i = $all.index($me[0]);
                if (i > -1) { focusEl($all.eq(i + 1)); }
            }, 0);
        });
        function rowFilled($row) {
            var hasAcct = !!$row.find('select[name$="-account"]').val();
            var amt = isJournal
                ? (num($row.find('input[name$="-debit"]')) > 0 || num($row.find('input[name$="-credit"]')) > 0)
                : num($row.find('input[name$="-amount"]')) > 0;
            return hasAcct && amt;
        }
        function rowBlank($row) {
            var hasAcct = !!$row.find('select[name$="-account"]').val();
            var anyAmt = isJournal
                ? (num($row.find('input[name$="-debit"]')) > 0 || num($row.find('input[name$="-credit"]')) > 0)
                : num($row.find('input[name$="-amount"]')) > 0;
            return !hasAcct && !anyAmt;
        }

        $(document).on('keydown', '.voucher-header-card input, .voucher-header-card select, .busy-table input, .busy-table select', function (e) {
            // Ctrl+Delete removes the current line
            if (e.key === 'Delete' && e.ctrlKey) {
                var $r = $(this).closest('.voucher-line-row');
                if ($r.length) {
                    e.preventDefault();
                    var $prev = $r.prevAll('.voucher-line-row:visible').first();
                    removeRow($r);
                    if ($prev.length) { focusEl($prev.find('input, select').filter(':visible').first()); }
                    return;
                }
            }
            if (e.key !== 'Enter' || e.isComposing) { return; }
            e.preventDefault();

            var $all = fields();
            var idx = $all.index(this);
            if (idx < 0) { return; }

            if (e.shiftKey) { focusEl($all.eq(idx - 1)); return; }

            var $me = $(this);
            var $row = $me.closest('.voucher-line-row');
            if (!$row.length) { focusEl($all.eq(idx + 1)); return; }   // header field

            var name = $me.attr('name') || '';
            var $save = $('#btn-save-main');

            // Empty account on a non-first line = "end of entry" -> go to Save
            if (/-account$/.test(name) && !$me.val() && rowBlank($row) && liveRows().index($row[0]) > 0) {
                $save.focus();
                return;
            }

            if (isJournal) {
                if (/-account$/.test(name)) {
                    var $dr = $row.find('input[name$="-debit"]'), $cr = $row.find('input[name$="-credit"]');
                    focusEl(num($cr) > 0 && !(num($dr) > 0) ? $cr : $dr);
                    return;
                }
                if (/-debit$/.test(name) && num($me) > 0) {      // Dr entered: skip Cr
                    focusEl($row.find('input[name$="-remarks"]'));
                    return;
                }
            }

            var $next = $all.eq(idx + 1);
            var $rowFields = $all.filter(function () { return $(this).closest('.voucher-line-row')[0] === $row[0]; });
            var isLastCell = $rowFields.last()[0] === this;

            if (isLastCell && $row.is(liveRows().last())) {
                if (rowFilled($row)) {
                    // Journal already balanced -> done, go to Save; otherwise new line
                    if (isJournal && Math.abs(otherTotals(null)) < 0.005) { $save.focus(); }
                    else { addRow(); }
                } else if (rowBlank($row)) {
                    $save.focus();
                }
                return;   // half-filled line: stay put
            }
            focusEl($next);
        });

        /* ---------- F2 save ---------- */
        $(document).on('keydown', function (e) {
            if (e.key === 'F2') { e.preventDefault(); $form.submit(); }
        });

        // Put blank Dr/Cr back to 0 so the DecimalField/NOT NULL columns are happy.
        $form.on('submit', function () {
            if (!isJournal) { return; }
            $form.find('input[name$="-debit"], input[name$="-credit"]').each(function () {
                if ($(this).val() === '') { $(this).val('0'); }
            });
        });

        /* ---------- initial paint ---------- */
        blankZeros($tbody);
        renumber();
        updateTotals();
        // Start typing straight away on desktop (don't pop the keyboard on phones)
        if (!$wrap.hasClass('is-mobile-layout') && !$form.find('.field-error, .errorlist').length) {
            focusEl($('#id_date'));
        }
    }

    function run() {
        var $ = window.jQuery || (window.django && window.django.jQuery);
        if ($) { $(document).ready(function () { init($); }); }
        else { setTimeout(run, 50); }
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', run); }
    else { run(); }
})();
