/**
 * Sale Voucher Interactive JS (Busy Software Desktop Grid & Mobile View Sync)
 */
(function() {
    'use strict';

    function initVoucherApp($) {
        if (!$) return;

        // View Switching
        // A single `is-mobile-layout` class on the wrapper decides whether the
        // busy-table renders as a desktop grid or reflows into mobile cards
        // (see sale_voucher.css). "Auto" watches the actual viewport width so
        // rotating a phone/tablet or resizing a window updates it live;
        // "Desktop"/"Mobile" pin it regardless of screen size.
        function isNarrowScreen() {
            return window.matchMedia('(max-width: 768px)').matches;
        }

        function applyLayoutClass() {
            var $wrapper = $('.sale-voucher-wrapper');
            var mobile;
            if ($wrapper.hasClass('force-desktop')) {
                mobile = false;
            } else if ($wrapper.hasClass('force-mobile')) {
                mobile = true;
            } else {
                mobile = isNarrowScreen();
            }
            $wrapper.toggleClass('is-mobile-layout', mobile);
        }

        window.setVoucherMode = function(mode) {
            var $wrapper = $('.sale-voucher-wrapper');
            $wrapper.removeClass('auto-responsive force-desktop force-mobile');
            $('.view-mode-btn').removeClass('active');

            if (mode === 'desktop') {
                $wrapper.addClass('force-desktop');
                $('#btn-mode-desktop').addClass('active');
            } else if (mode === 'mobile') {
                $wrapper.addClass('force-mobile');
                $('#btn-mode-mobile').addClass('active');
            } else {
                mode = 'auto';
                $wrapper.addClass('auto-responsive');
                $('#btn-mode-auto').addClass('active');
            }

            applyLayoutClass();
            try { window.localStorage.setItem('voucherViewMode', mode); } catch (e) { /* private mode / disabled storage - ignore */ }
        };

        // Restore the user's last chosen mode (defaults to Auto)
        var savedMode = 'auto';
        try { savedMode = window.localStorage.getItem('voucherViewMode') || 'auto'; } catch (e) { /* ignore */ }
        setVoucherMode(savedMode);

        // Keep "Auto" mode in sync with the real viewport size
        $(window).on('resize orientationchange', applyLayoutClass);

        // Helper: Round to 2 decimal places
        function round2(val) {
            return Math.round(((parseFloat(val) || 0) + Number.EPSILON) * 100) / 100;
        }

        // Helper: Format currency string
        function fmtMoney(val) {
            var n = round2(val);
            var prefix = n < 0 ? '- ₹ ' : '₹ ';
            return prefix + Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }

        // Check if Sale Type is Tax Inclusive
        function isTaxInclusive() {
            var $select = $('#id_sale_type, #id_purchase_type').first();
            if (!$select.length) return false;
            var $opt = $select.find('option:selected');
            return $opt.data('tax-inclusive') === true || $opt.data('tax-inclusive') === '1' || $opt.data('tax-inclusive') === 1;
        }

        // Check if Sale Type has Multirate billing enabled (mirrors
        // voucher_totals()'s multirate param in models.py)
        function isMultirate() {
            var $select = $('#id_sale_type, #id_purchase_type').first();
            if (!$select.length) return false;
            var $opt = $select.find('option:selected');
            return $opt.data('multirate') === true || $opt.data('multirate') === '1' || $opt.data('multirate') === 1;
        }

        // Free Quantity Scheme Parser (e.g., "10+2")
        function parseQty(raw) {
            var str = (raw || '').toString().trim();
            var match = str.match(/^([0-9]*\.?[0-9]+)\s*(?:\+\s*([0-9]*\.?[0-9]+))?$/);
            if (!match) {
                return { billed: parseFloat(str) || 0, free: 0 };
            }
            return {
                billed: parseFloat(match[1]) || 0,
                free: match[2] ? (parseFloat(match[2]) || 0) : 0
            };
        }

        // Calculate line amounts
        function calcLineAmounts(qtyRaw, rateRaw, discRaw, taxPercentRaw) {
            var pQty = parseQty(qtyRaw);
            var qty = pQty.billed;
            var rate = parseFloat(rateRaw) || 0;
            var disc = parseFloat(discRaw) || 0;
            var taxPct = parseFloat(taxPercentRaw) || 0;
            var taxInclusive = isTaxInclusive();

            var grossBasic = qty * rate;
            var grossAfterDisc = grossBasic - disc;
            var basicBase, afterDiscBase, taxAmt, net;

            if (taxInclusive) {
                var divisor = 1 + (taxPct / 100);
                basicBase = (divisor > 0 && grossBasic > 0) ? (grossBasic / divisor) : grossBasic;
                afterDiscBase = (divisor > 0 && grossAfterDisc > 0) ? (grossAfterDisc / divisor) : grossAfterDisc;
                taxAmt = grossAfterDisc - afterDiscBase;
                net = grossAfterDisc;
            } else {
                basicBase = grossBasic;
                afterDiscBase = grossAfterDisc;
                taxAmt = afterDiscBase * (taxPct / 100);
                net = afterDiscBase + taxAmt;
            }

            return {
                billedQty: qty,
                freeQty: pQty.free,
                totalQty: qty + pQty.free,
                basicAmt: round2(basicBase),
                afterDiscBase: round2(afterDiscBase),
                taxAmt: round2(taxAmt),
                netAmt: round2(net)
            };
        }

        // Reads one sundry row's selected Bill Sundry's type/apply-on/
        // amount-of/default-value, tagged onto each <option> by admin.py's
        // BillSundrySelect widget.
        function readSundryOption($sRow) {
            var $sundrySelect = $sRow.find('.v-input-sundry, select[name$="-bill_sundry"]');
            var $opt = $sundrySelect.find('option:selected');
            return {
                id: $sundrySelect.val(),
                type: $opt.attr('data-type') || 'ADDITIVE',
                amountOf: $opt.attr('data-amount-of') || 'PERCENT',
                defaultVal: parseFloat($opt.attr('data-default-value')) || 0,
                applyOn: $opt.attr('data-apply-on') || 'ITEM_BASIC'
            };
        }

        // Resolves a sundry's unsigned amount (entered value, or the
        // default against the right base) and applies its sign. Mirrors
        // compute_sundry_amount() in models.py. When `writeBack` is true and
        // the amount field was blank, the computed default is written into
        // it (same UX as before - the field shows what it will actually post).
        function resolveSundryAmount(meta, $amtInput, bases, previous, running, writeBack) {
            var rawVal = $amtInput.val();
            var entered = parseFloat(rawVal);
            var amount = 0;

            if (rawVal !== '' && !isNaN(entered)) {
                amount = Math.abs(entered);
            } else if (meta.amountOf === 'ABSOLUTE') {
                amount = meta.defaultVal;
                if (writeBack) { $amtInput.val(amount.toFixed(2)); }
            } else {
                var applyMap = {
                    'ITEM_BASIC': bases.ITEM_BASIC,
                    'ITEM_DISCOUNT': bases.ITEM_DISCOUNT,
                    'ITEM_AMOUNT': bases.ITEM_AMOUNT,
                    'TAX_AMOUNT': bases.TAX_AMOUNT,
                    'ITEM_NET': bases.ITEM_NET,
                    'BILL_AMOUNT': running,
                    'PREVIOUS_SUNDRY': previous
                };
                var base = (applyMap[meta.applyOn] !== undefined) ? applyMap[meta.applyOn] : bases.ITEM_BASIC;
                amount = round2(base * meta.defaultVal / 100);
                if (writeBack) { $amtInput.val(amount.toFixed(2)); }
            }

            return (meta.type === 'SUBTRACTIVE') ? -amount : amount;
        }

        // A sundry counts as an overall pre-tax bill discount only when the
        // Sale Type has Multirate on AND the sundry is Subtractive + applied
        // on Item Basic amount - exactly the signal voucher_totals() uses.
        function isPretaxDiscount(meta, multirate) {
            return multirate && meta.type === 'SUBTRACTIVE' && meta.applyOn === 'ITEM_BASIC';
        }

        // Calculate row & voucher totals (exact mirror of backend voucher_totals in models.py)
        function updateCalculations() {
            var totalBasic = 0;
            var totalDisc = 0;
            var totalTaxable = 0;
            var totalTax = 0;
            var totalItemsNet = 0;
            var lineBases = []; // { afterDiscBase, taxPct } per item row, for the multirate redistribution pass

            // 1. Loop over item rows (always shows each line's own plain
            // figures - a Multirate discount never changes a line's own
            // displayed basic/tax/net, only the voucher-level summary below,
            // exactly matching SaleItem's own properties server side)
            $('.item-form-row:not(.empty-form-row)').each(function() {
                var $row = $(this);
                var qtyVal = $row.find('.v-input-qty, input[name$="-quantity"]').val();
                var rateVal = $row.find('.v-input-rate, input[name$="-rate"]').val();
                var discVal = $row.find('.v-input-disc, input[name$="-discount"]').val();
                var taxVal = $row.find('.v-input-tax, input[name$="-tax"]').val();

                var res = calcLineAmounts(qtyVal, rateVal, discVal, taxVal);

                // Update row display outputs
                $row.find('.v-out-basic').text(res.basicAmt.toFixed(2));
                $row.find('.v-out-tax').text(res.taxAmt.toFixed(2));
                $row.find('.v-out-net').text(res.netAmt.toFixed(2));
                $row.find('.v-out-totqty').text(res.totalQty);

                totalBasic += res.basicAmt;
                totalDisc += (parseFloat(discVal) || 0);
                totalTaxable += res.afterDiscBase;
                totalTax += res.taxAmt;
                totalItemsNet += res.netAmt;
                lineBases.push({ afterDiscBase: res.afterDiscBase, taxPct: parseFloat(taxVal) || 0 });
            });

            var multirate = isMultirate();
            var bases = {
                'ITEM_BASIC': totalBasic,
                'ITEM_DISCOUNT': totalDisc,
                'ITEM_AMOUNT': totalTaxable,
                'TAX_AMOUNT': totalTax,
                'ITEM_NET': totalItemsNet
            };

            var $sundryRows = $('.sundry-form-row:not(.empty-sundry-row)');

            // 2. Pass 1: find Multirate pre-tax discount sundries and total
            // up how much needs to come off before GST - mirrors
            // voucher_totals()'s first pass exactly. Uses the ORIGINAL
            // (pre-redistribution) item bases, same as every "Item basic
            // amount" sundry already does.
            var rowInfo = [];
            var totalPretaxDiscount = 0;
            $sundryRows.each(function() {
                var $sRow = $(this);
                var meta = readSundryOption($sRow);
                var info = { $row: $sRow, meta: meta, isPretax: false, signed: 0 };
                if (meta.id && !isNaN(meta.id)) {
                    info.isPretax = isPretaxDiscount(meta, multirate);
                    if (info.isPretax) {
                        var $amtInput = $sRow.find('.v-input-sundry-amt, input[name$="-amount"]');
                        info.signed = resolveSundryAmount(meta, $amtInput, bases, 0, totalItemsNet, false);
                        if (info.signed < 0) { totalPretaxDiscount += -info.signed; }
                    }
                }
                $sRow.find('.sundry-multirate-hint').toggle(info.isPretax);
                rowInfo.push(info);
            });

            // 3. Recompute item amount/tax/net if there's a pretax discount
            // to spread - proportionally by each line's share of the (post
            // item-discount) basic amount, tax recalculated per line on the
            // reduced base, last line absorbs the rounding remainder.
            if (multirate && totalPretaxDiscount > 0 && totalTaxable > 0) {
                var totalBase = totalTaxable;
                var remaining = totalPretaxDiscount;
                var newItemAmount = 0;
                var newTax = 0;
                lineBases.forEach(function(lb, i) {
                    var lineShare;
                    if (i === lineBases.length - 1) {
                        lineShare = remaining; // last line absorbs rounding remainder
                    } else {
                        var ratio = totalBase ? (lb.afterDiscBase / totalBase) : 0;
                        lineShare = round2(totalPretaxDiscount * ratio);
                        remaining = round2(remaining - lineShare);
                    }
                    var newLineBase = lb.afterDiscBase - lineShare;
                    if (newLineBase < 0) { newLineBase = 0; }
                    var newLineTax = round2(newLineBase * (lb.taxPct / 100));
                    newItemAmount += newLineBase;
                    newTax += newLineTax;
                });
                totalTaxable = round2(newItemAmount);
                totalTax = round2(newTax);
                totalItemsNet = round2(newItemAmount + newTax);
                bases.ITEM_AMOUNT = totalTaxable;
                bases.TAX_AMOUNT = totalTax;
                bases.ITEM_NET = totalItemsNet;
            }

            // 4. Pass 2: walk sundry rows again for the final running total.
            // Pretax rows are excluded here (already folded into totalTax/
            // totalItemsNet above) so they aren't counted twice - matching
            // voucher_totals()'s sundry_amount exactly. Non-pretax rows use
            // `bases` as it now stands, so e.g. a Freight sundry based on
            // "Item amount" correctly sees the post-discount figure too.
            var running = totalItemsNet;
            var previous = 0;
            var totalSundry = 0;
            rowInfo.forEach(function(info) {
                if (!info.meta.id || isNaN(info.meta.id)) { return; }
                if (info.isPretax) { return; }
                var $amtInput = info.$row.find('.v-input-sundry-amt, input[name$="-amount"]');
                var signed = resolveSundryAmount(info.meta, $amtInput, bases, previous, running, true);
                totalSundry += signed;
                running = round2(running + signed);
                previous = signed;
            });

            var grandNet = running;

            // Update Voucher Totals Summary Box (Desktop & Mobile)
            $('#v-sum-basic').text(fmtMoney(totalBasic));
            $('#v-sum-disc').text(fmtMoney(totalDisc));
            $('#v-sum-tax').text(fmtMoney(totalTax));
            $('#v-sum-sundry').text(fmtMoney(totalSundry));
            $('.v-sum-grand-net').text(fmtMoney(grandNet));
        }

        // Live AJAX Item Lookup
        function fetchItemDetails($itemSelect) {
            var itemId = $itemSelect.val();
            var $row = $itemSelect.closest('.item-form-row');
            if (!itemId || isNaN(itemId) || parseInt(itemId) <= 0) return;

            var adminPrefix = window.location.pathname.split('/masters/')[0];
            $.ajax({
                url: adminPrefix + '/masters/item-detail/' + itemId + '/',
                type: 'GET',
                dataType: 'json',
                success: function(data) {
                    if (data.success) {
                        // 1. Set Unit
                        var $unitSelect = $row.find('.v-input-unit, select[name$="-unit"]');
                        if ($unitSelect.length && data.main_unit_id) {
                            if (!$unitSelect.find("option[value='" + data.main_unit_id + "']").length) {
                                var newOption = new Option(data.main_unit_name, data.main_unit_id, true, true);
                                $unitSelect.append(newOption);
                            }
                            $unitSelect.val(data.main_unit_id);
                        }

                        // 2. Set Rate (Sale Price by default; Purchase vouchers set
                        // data-price-field="purchase_price" on the wrapper)
                        var priceField = $('.sale-voucher-wrapper').attr('data-price-field') || 'sale_price';
                        if (data[priceField] !== undefined) {
                            $row.find('.v-input-rate, input[name$="-rate"]').val(parseFloat(data[priceField]).toFixed(2));
                        }

                        // 3. Set Tax Rate
                        if (data.tax !== undefined) {
                            $row.find('.v-input-tax, input[name$="-tax"]').val(parseFloat(data.tax).toFixed(2));
                        }

                        // 4. Default Quantity to 1 if empty or 0
                        var $qtyInput = $row.find('.v-input-qty, input[name$="-quantity"]');
                        if (!$qtyInput.val() || parseFloat($qtyInput.val()) === 0) {
                            $qtyInput.val("1");
                        }

                        // Recalculate immediately
                        updateCalculations();
                    }
                }
            });
        }

        // Store initial item IDs so spurious change events on page load do NOT overwrite saved rates
        $('.v-input-item, select[name$="-item"]').each(function() {
            var val = $(this).val();
            $(this).data('previous-item-id', val ? String(val) : '');
        });

        // Initial setup
        updateCalculations();

        // Listen for user item selection change
        function handleItemChange($itemSelect) {
            var savedId = $itemSelect.attr('data-saved-item-id') || $itemSelect.data('saved-item-id');
            var prevId = $itemSelect.data('previous-item-id');
            var newId = $itemSelect.val() ? String($itemSelect.val()) : '';

            // If this is an existing saved line and the item was NOT changed: NEVER fetch or overwrite!
            if (savedId && String(savedId) === newId) {
                return;
            }

            // If value didn't change: ignore spurious event
            if (prevId !== undefined && prevId === newId) {
                return;
            }

            $itemSelect.data('previous-item-id', newId);
            fetchItemDetails($itemSelect);
        }

        $(document).on('change select2:select', '.v-input-item, select[name$="-item"], .field-item select', function() {
            handleItemChange($(this));
        });

        // When Bill Sundry dropdown changes, auto-fill default value and recalculate
        $(document).on('change', '.v-input-sundry, select[name$="-bill_sundry"]', function() {
            var $sRow = $(this).closest('.sundry-form-row');
            $sRow.find('.v-input-sundry-amt, input[name$="-amount"]').val('');
            updateCalculations();
        });

        // Listen for value inputs to recalculate instantly
        $(document).on('input change keyup', '.v-input-qty, .v-input-rate, .v-input-disc, .v-input-tax, .v-input-sundry-amt, #id_sale_type, #id_purchase_type, input[name$="-quantity"], input[name$="-rate"], input[name$="-discount"], input[name$="-tax"]', function() {
            updateCalculations();
        });

        // Keyboard Navigation in Busy Grid
        $(document).on('keydown', '.busy-table input, .busy-table select', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                var $inputs = $('.busy-table input:not([readonly]), .busy-table select');
                var idx = $inputs.index(this);
                if (idx > -1 && idx < $inputs.length - 1) {
                    $inputs.eq(idx + 1).focus().select();
                } else {
                    $('#btn-add-item-row').click();
                }
            }
        });

        // ---- Item Details panel: item info + last 5 sale / purchase rates ----
        // Read-only. Follows the cursor: focusing any cell of an item line (or
        // choosing an item) loads that item's details. "Current Party" limits
        // the rate history to the party picked in the header; "All Parties"
        // shows the latest rates across every party.
        var infoScope = 'party';
        var infoItemId = '';
        var infoReq = null;

        function esc(v) {
            return String(v === null || v === undefined ? '' : v)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }
        function num2(v) { return (parseFloat(v) || 0).toFixed(2); }
        function qtyTxt(r) {
            var q = parseFloat(r.qty) || 0;
            return (q % 1 === 0 ? q.toString() : q.toFixed(2)) + (r.unit ? ' ' + esc(r.unit) : '');
        }

        function renderRateRows(selector, rows) {
            var showParty = infoScope === 'all';
            var html = '';
            if (!rows || !rows.length) {
                html = '<tr><td colspan="5" class="iip-empty">No records</td></tr>';
            } else {
                rows.forEach(function(r) {
                    html += '<tr><td>' + esc(r.date) + '</td><td>' + esc(r.invoice_no) + '</td>' +
                        '<td class="iip-party-col" title="' + esc(r.party) + '">' + esc(r.party) + '</td>' +
                        '<td class="r">' + qtyTxt(r) + '</td><td class="r iip-rate">' + num2(r.rate) + '</td></tr>';
                });
            }
            $(selector).html(html);
            $('#item-info-panel').toggleClass('show-party', showParty);
        }

        function renderItemInfo(data) {
            var it = data.item || {};
            $('#iip-name').text(it.name || 'Item Details');
            var bits = [];
            function chip(label, value) {
                if (value === '' || value === null || value === undefined) return;
                bits.push('<span class="iip-chip"><em>' + label + '</em>' + esc(value) + '</span>');
            }
            chip('Group', it.group);
            chip('HSN', it.hsn);
            chip('Unit', it.unit);
            chip('Tax', it.tax !== undefined ? num2(it.tax) + '%' : '');
            chip('MRP', it.mrp ? num2(it.mrp) : '');
            chip('Std Sale', num2(it.sale_price));
            chip('Std Purchase', num2(it.purchase_price));
            $('#iip-meta').html(bits.join(''));
            renderRateRows('#iip-sales', data.sales);
            renderRateRows('#iip-purchases', data.purchases);
        }

        function loadItemInfo(itemId) {
            if (!itemId || isNaN(itemId) || parseInt(itemId, 10) <= 0) { return; }
            infoItemId = String(itemId);
            var adminPrefix = window.location.pathname.split('/masters/')[0];
            var params = {};
            var acc = $('#id_account').val();
            if (infoScope === 'party' && acc) { params.account = acc; }
            if (infoReq && infoReq.abort) { infoReq.abort(); }
            infoReq = $.ajax({
                url: adminPrefix + '/masters/item-history/' + infoItemId + '/',
                type: 'GET',
                data: params,
                dataType: 'json',
                success: function(data) { if (data && data.success) { renderItemInfo(data); } }
            });
        }

        // Cursor moves into any cell of an item line -> show that item
        $(document).on('focusin', '.item-form-row', function() {
            var id = $(this).find('.v-input-item, select[name$="-item"]').first().val();
            if (id && String(id) !== infoItemId) { loadItemInfo(id); }
        });
        // Item chosen / changed in the focused line
        $(document).on('change select2:select', '.v-input-item, select[name$="-item"]', function() {
            var id = $(this).val();
            if (id) { loadItemInfo(id); }
        });
        // Party changed -> refresh "Current Party" history for the shown item
        $(document).on('change select2:select', '#id_account', function() {
            if (infoItemId && infoScope === 'party') { loadItemInfo(infoItemId); }
        });
        // Current Party / All Parties toggle
        $(document).on('click', '.iip-scope-btn', function(e) {
            e.preventDefault();
            infoScope = $(this).attr('data-scope') === 'all' ? 'all' : 'party';
            $('.iip-scope-btn').removeClass('active');
            $(this).addClass('active');
            if (infoItemId) { loadItemInfo(infoItemId); }
        });

        // Global F2 Shortcut for Save
        $(document).on('keydown', function(e) {
            if (e.key === 'F2') {
                e.preventDefault();
                $('#sale_form').submit();
            }
        });

        // Dynamic Item Row Addition
        $(document).on('click', '#btn-add-item-row, #btn-add-item-mobile', function(e) {
            e.preventDefault();
            // Read from <script type="text/html"> — browser preserves <tr> as raw text
            var $tplScript = $('#item-empty-form-template');
            var emptyTemplateHtml = $tplScript.length ? $tplScript.text() : '';

            if (!emptyTemplateHtml || !emptyTemplateHtml.trim()) {
                alert('Item row template not found. Please refresh the page.');
                return;
            }

            var $totalForms = $('#id_items-TOTAL_FORMS');
            var formCount = parseInt($totalForms.val()) || 0;

            var newRowHtml = emptyTemplateHtml.replace(/__prefix__/g, formCount);
            var $newRow = $(newRowHtml);
            $('#busy-items-tbody').append($newRow);

            $totalForms.val(formCount + 1);

            // Update row number display
            $newRow.find('.row-num').text(formCount + 1);

            // Initialize previous item id for change tracking
            $newRow.find('.v-input-item, select[name$="-item"]').data('previous-item-id', '');

            // Focus item select in new row
            $newRow.find('select[name$="-item"]').focus();
            updateCalculations();
        });

        // Dynamic Bill Sundry Row Addition
        $(document).on('click', '#btn-add-sundry-row', function(e) {
            e.preventDefault();
            var $tplScript = $('#sundry-empty-form-template');
            var emptySundryHtml = $tplScript.length ? $tplScript.text() : '';

            if (!emptySundryHtml || !emptySundryHtml.trim()) {
                alert('Sundry row template not found. Please refresh the page.');
                return;
            }

            var $totalForms = $('#id_bill_sundries-TOTAL_FORMS');
            var formCount = parseInt($totalForms.val()) || 0;

            var newRowHtml = emptySundryHtml.replace(/__prefix__/g, formCount);
            var $newRow = $(newRowHtml);
            $('#busy-sundries-tbody').append($newRow);
            $totalForms.val(formCount + 1);
            updateCalculations();
        });

        // Re-sequence the JS-added (not-yet-saved) rows after one is removed, so
        // there's no gap in the -0-, -1-, -2- form indices. Existing/saved rows
        // (identified by having a DELETE checkbox) are never renumbered - they
        // keep their original index and are only hidden + flagged for deletion.
        // Without this, deleting a newly-added row that wasn't the LAST one
        // added left a hole in the formset indices, and Django would then
        // demand "this field is required" for a row that no longer exists on
        // the page - the save error seen when modifying a bill.
        function reindexNewRows($tbody, rowSelector, prefix, $totalForms) {
            var initialCount = parseInt($totalForms.data('initial-count'), 10);
            if (isNaN(initialCount)) {
                // First time: whatever isn't a "new" row right now defines the
                // boundary. Existing rows always have a DELETE checkbox.
                initialCount = 0;
                $tbody.children(rowSelector).each(function() {
                    if ($(this).find('input[type="checkbox"][name$="-DELETE"]').length) {
                        initialCount++;
                    }
                });
                $totalForms.data('initial-count', initialCount);
            }

            var idx = initialCount;
            var prefixRe = new RegExp(prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '-\\d+-');

            $tbody.children(rowSelector).each(function() {
                var $row = $(this);
                var isExisting = $row.find('input[type="checkbox"][name$="-DELETE"]').length > 0;
                if (isExisting) { return; } // leave saved rows' indices untouched

                var newPrefix = prefix + '-' + idx + '-';
                $row.find('[name]').each(function() {
                    var $el = $(this);
                    var name = $el.attr('name');
                    if (name && prefixRe.test(name)) {
                        $el.attr('name', name.replace(prefixRe, newPrefix));
                    }
                });
                $row.find('[id]').each(function() {
                    var $el = $(this);
                    var id = $el.attr('id');
                    if (id && id.indexOf('id_' + prefix + '-') === 0) {
                        $el.attr('id', id.replace(prefixRe, newPrefix));
                    }
                });
                idx++;
            });

            $totalForms.val(idx);
        }

        // Delete Row
        $(document).on('click', '.btn-delete-item-row', function(e) {
            e.preventDefault();
            var $row = $(this).closest('.item-form-row');
            var $deleteCheckbox = $row.find('input[type="checkbox"][name$="-DELETE"]');
            if ($deleteCheckbox.length) {
                $deleteCheckbox.prop('checked', true);
                $row.hide().addClass('empty-form-row');
            } else {
                $row.remove();
                reindexNewRows($('#busy-items-tbody'), '.item-form-row', 'items', $('#id_items-TOTAL_FORMS'));
            }
            updateCalculations();
        });

        $(document).on('click', '.btn-delete-sundry-row', function(e) {
            e.preventDefault();
            var $sRow = $(this).closest('.sundry-form-row');
            var $deleteCheckbox = $sRow.find('input[type="checkbox"][name$="-DELETE"]');
            if ($deleteCheckbox.length) {
                $deleteCheckbox.prop('checked', true);
                $sRow.hide().addClass('empty-sundry-row');
            } else {
                $sRow.remove();
                reindexNewRows($('#busy-sundries-tbody'), '.sundry-form-row', 'bill_sundries', $('#id_bill_sundries-TOTAL_FORMS'));
            }
            updateCalculations();
        });
    }

    function runInit() {
        var $ = window.jQuery || (window.django && window.django.jQuery);
        if ($) {
            $(document).ready(function() {
                initVoucherApp($);
            });
        } else {
            setTimeout(runInit, 50);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', runInit);
    } else {
        runInit();
    }
})();
