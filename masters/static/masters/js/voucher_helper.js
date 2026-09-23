(function($) {
    'use strict';

    function isTaxInclusive() {
        var $typeSelect = $('#id_sale_type, #id_purchase_type').first();
        if (!$typeSelect.length) return false;
        var $opt = $typeSelect.find('option:selected');
        if (!$opt.length) return false;
        return $opt.data('tax-inclusive') === true || $opt.data('tax-inclusive') === '1' || $opt.data('tax-inclusive') === 1;
    }

    function calcLine(qty, rate, discount, taxPercent, taxInclusive) {
        var basicGross = qty * rate;
        var afterDiscGross = basicGross - discount;
        var basicBase, afterDiscBase, taxAmt, net;

        if (taxInclusive) {
            var divisor = 1 + (taxPercent / 100);
            basicBase = (divisor > 0 && basicGross > 0) ? (basicGross / divisor) : basicGross;
            afterDiscBase = (divisor > 0 && afterDiscGross > 0) ? (afterDiscGross / divisor) : afterDiscGross;
            taxAmt = afterDiscGross - afterDiscBase;
            net = afterDiscGross;
        } else {
            basicBase = basicGross;
            afterDiscBase = afterDiscGross;
            taxAmt = afterDiscBase * (taxPercent / 100);
            net = afterDiscBase + taxAmt;
        }

        return {
            basicAmount: round2(basicBase),
            amountAfterDiscount: round2(afterDiscBase),
            taxAmount: round2(taxAmt),
            netAmount: round2(net),
            afterDiscGross: round2(afterDiscGross),
        };
    }

    function round2(v) {
        return Math.round((v + Number.EPSILON) * 100) / 100;
    }

    $(document).ready(function() {
        // Event delegation for item selection changes
        $(document).on('change', '.field-item select', function() {
            var $select = $(this);
            var item_id = $select.val();
            var $row = $select.closest('tr');

            if (!item_id || isNaN(item_id)) {
                // Clear row values if item is cleared
                $row.find('.field-tax input').val('0.00');
                $row.find('.field-rate input').val('0.00');
                calculateRowTotals($row);
                return;
            }

            // Fetch item details from custom API using relative path
            var adminPrefix = window.location.pathname.split('/masters/')[0];
            $.ajax({
                url: adminPrefix + '/masters/item-detail/' + item_id + '/',
                type: 'GET',
                dataType: 'json',
                success: function(data) {
                    if (data.success) {
                        // 1. Populate Unit (Select2 / standard select)
                        var $unitSelect = $row.find('.field-unit select');
                        if ($unitSelect.length) {
                            if (!$unitSelect.find("option[value='" + data.main_unit_id + "']").length) {
                                var newOption = new Option(data.main_unit_name, data.main_unit_id, true, true);
                                $unitSelect.append(newOption).trigger('change');
                            } else {
                                $unitSelect.val(data.main_unit_id).trigger('change');
                            }
                        }

                        // 2. Populate Rate based on Purchase vs Sale page
                        var isPurchase = window.location.pathname.indexOf('/purchase/') !== -1;
                        var rate = isPurchase ? data.purchase_price : data.sale_price;
                        $row.find('.field-rate input').val(rate.toFixed(2)).trigger('change');

                        // 3. Populate Tax
                        $row.find('.field-tax input').val(data.tax.toFixed(2)).trigger('change');

                        // Recalculate everything for the row
                        calculateRowTotals($row);
                    }
                },
                error: function(xhr, status, error) {
                    console.error('Failed to fetch item details:', error);
                }
            });
        });

        // Listen for changes in input fields to calculate row totals and voucher totals dynamically
        $(document).on('input change keyup', 
            '#items-group tbody tr.form-row .field-quantity input, ' +
            '#items-group tbody tr.form-row .field-rate input, ' +
            '#items-group tbody tr.form-row .field-discount input, ' +
            '#items-group tbody tr.form-row .field-tax input', 
            function() {
                var $row = $(this).closest('tr');
                calculateRowTotals($row);
            }
        );

        // Recalculate everything when the sale/purchase type changes (affects tax_inclusive)
        $(document).on('change', '#id_sale_type, #id_purchase_type', function() {
            $('#items-group tbody tr.form-row:not(.empty-form)').each(function() {
                calculateRowTotals($(this));
            });
            calculateVoucherTotals();
        });

        $(document).on('input change keyup', '#bill_sundries-group tbody tr.form-row .field-amount input', function() {
            calculateVoucherTotals();
        });

        // Initialize calculations on page load
        $('#items-group tbody tr.form-row:not(.empty-form)').each(function() {
            calculateRowTotals($(this));
        });
        calculateVoucherTotals();

        // Listen for new inline rows added
        $(document).on('formset:added', function(event, $row, formsetName) {
            if (formsetName === 'items' || formsetName === 'bill_sundries') {
                calculateRowTotals($row);
                calculateVoucherTotals();
            }
        });
    });

    // The Quantity box accepts a plain number ('10') or a Busy/Tally style
    // free-quantity scheme ('10+2' = 10 billed + 2 free). Only the billed
    // part is ever billed/taxed; the free part only feeds Total Qty.
    function parseQtyInput(raw) {
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

    function calculateRowTotals($row) {
        if ($row.hasClass('empty-form')) return;

        var taxInclusive = isTaxInclusive();
        var parsedQty = parseQtyInput($row.find('.field-quantity input').val());
        var qty = parsedQty.billed;
        var freeQty = parsedQty.free;
        var rate = parseFloat($row.find('.field-rate input').val()) || 0;
        var discount = parseFloat($row.find('.field-discount input').val()) || 0;
        var taxPercent = parseFloat($row.find('.field-tax input').val()) || 0;

        // Free quantity (e.g. a "10+2" scheme) moves stock but is never
        // billed, so it stays out of every amount below - only the
        // informational Total Qty cell reflects it.
        var r = calcLine(qty, rate, discount, taxPercent, taxInclusive);

        // Display calculations in read-only cells
        updateReadonlyText($row.find('.field-total_quantity'), qty + freeQty);
        updateReadonlyText($row.find('.field-basic_amount'), r.basicAmount);
        updateReadonlyText($row.find('.field-amount_after_discount'), r.amountAfterDiscount);
        updateReadonlyText($row.find('.field-tax_amount'), r.taxAmount);
        updateReadonlyText($row.find('.field-net_amount'), r.netAmount);

        // Recalculate voucher totals
        calculateVoucherTotals();
    }

    function calculateVoucherTotals() {
        var taxInclusive = isTaxInclusive();
        var totalBasic = 0;
        var totalDiscount = 0;
        var totalAmount = 0;
        var totalTax = 0;

        $('#items-group tbody tr.form-row:not(.empty-form)').each(function() {
            var $row = $(this);
            var parsedQty = parseQtyInput($row.find('.field-quantity input').val());
            var qty = parsedQty.billed;
            var rate = parseFloat($row.find('.field-rate input').val()) || 0;
            var discount = parseFloat($row.find('.field-discount input').val()) || 0;
            var taxPercent = parseFloat($row.find('.field-tax input').val()) || 0;

            var r = calcLine(qty, rate, discount, taxPercent, taxInclusive);

            totalBasic += r.basicAmount;
            totalDiscount += discount;
            totalAmount += r.amountAfterDiscount;
            totalTax += r.taxAmount;
        });

        var totalSundry = 0;
        $('#bill_sundries-group tbody tr.form-row:not(.empty-form)').each(function() {
            var $row = $(this);
            var amt = parseFloat($row.find('.field-amount input').val()) || 0;
            totalSundry += amt;
        });

        var netAmount = totalAmount + totalTax + totalSundry;

        // Update voucher totals fields
        updateReadonlyText($('.field-item_basic_amount'), totalBasic);
        updateReadonlyText($('.field-item_discount_amount'), totalDiscount);
        updateReadonlyText($('.field-item_amount'), totalAmount);
        updateReadonlyText($('.field-tax_amount'), totalTax);
        updateReadonlyText($('.field-sundry_amount'), totalSundry);
        updateReadonlyText($('.field-net_amount'), netAmount);
    }

    function updateReadonlyText($container, val) {
        var formatted = val.toFixed(2);
        // Targets Django's readonly divs or paragraphs inside the field container
        var $el = $container.find('.readonly, p, div');
        if ($el.length) {
            $el.text(formatted);
        } else {
            // Fallback: update cell text if no specific element is found
            $container.text(formatted);
        }
    }

})(django.jQuery);
