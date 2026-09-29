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
            return '₹ ' + round2(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }

        // Check if Sale Type is Tax Inclusive
        function isTaxInclusive() {
            var $select = $('#id_sale_type');
            if (!$select.length) return false;
            var $opt = $select.find('option:selected');
            return $opt.data('tax-inclusive') === true || $opt.data('tax-inclusive') === '1' || $opt.data('tax-inclusive') === 1;
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

        // Calculate row & voucher totals
        function updateCalculations() {
            var totalBasic = 0;
            var totalDisc = 0;
            var totalTax = 0;
            var totalItemsNet = 0;

            // Loop over item rows
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
                totalTax += res.taxAmt;
                totalItemsNet += res.netAmt;
            });

            // Loop over Bill Sundries
            var totalSundry = 0;
            $('.sundry-form-row:not(.empty-sundry-row)').each(function() {
                var $sRow = $(this);
                var amt = parseFloat($sRow.find('.v-input-sundry-amt, input[name$="-amount"]').val()) || 0;
                totalSundry += amt;
            });

            var grandNet = totalItemsNet + totalSundry;

            // Update Voucher Totals Summary Box (Desktop)
            $('#v-sum-basic').text(fmtMoney(totalBasic));
            $('#v-sum-disc').text(fmtMoney(totalDisc));
            $('#v-sum-tax').text(fmtMoney(totalTax));
            $('#v-sum-sundry').text(fmtMoney(totalSundry));
            // .v-sum-grand-net appears twice in the markup: once in the desktop
            // totals card, once in the mobile sticky bar. Both get updated here.
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

                        // 2. Set Rate (Default Sale Price)
                        if (data.sale_price !== undefined) {
                            var price = parseFloat(data.sale_price) || 0;
                            var $rateInput = $row.find('.v-input-rate, input[name$="-rate"]');
                            // If the master price is 0 and input already has a rate, keep it unless new line
                            if (price > 0 || !$rateInput.val() || parseFloat($rateInput.val()) === 0) {
                                $rateInput.val(price.toFixed(2));
                            }
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
            var prevId = $itemSelect.data('previous-item-id');
            var newId = $itemSelect.val() ? String($itemSelect.val()) : '';
            if (prevId !== undefined && prevId === newId) {
                // Item didn't change (spurious event triggered on page load/select2 init/focus)
                return;
            }
            $itemSelect.data('previous-item-id', newId);
            fetchItemDetails($itemSelect);
        }

        $(document).on('change select2:select', '.v-input-item, select[name$="-item"], .field-item select', function() {
            handleItemChange($(this));
        });

        // Listen for value inputs to recalculate instantly
        $(document).on('input change keyup', '.v-input-qty, .v-input-rate, .v-input-disc, .v-input-tax, .v-input-sundry-amt, #id_sale_type, input[name$="-quantity"], input[name$="-rate"], input[name$="-discount"], input[name$="-tax"]', function() {
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
