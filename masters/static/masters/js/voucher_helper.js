(function($) {
    'use strict';

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

    function calculateRowTotals($row) {
        if ($row.hasClass('empty-form')) return;

        var qty = parseFloat($row.find('.field-quantity input').val()) || 0;
        var rate = parseFloat($row.find('.field-rate input').val()) || 0;
        var discount = parseFloat($row.find('.field-discount input').val()) || 0;
        var taxPercent = parseFloat($row.find('.field-tax input').val()) || 0;

        var basicAmount = qty * rate;
        var amountAfterDiscount = basicAmount - discount;
        var taxAmount = amountAfterDiscount * (taxPercent / 100);
        var netAmount = amountAfterDiscount + taxAmount;

        // Display calculations in read-only cells
        updateReadonlyText($row.find('.field-basic_amount'), basicAmount);
        updateReadonlyText($row.find('.field-amount_after_discount'), amountAfterDiscount);
        updateReadonlyText($row.find('.field-tax_amount'), taxAmount);
        updateReadonlyText($row.find('.field-net_amount'), netAmount);

        // Recalculate voucher totals
        calculateVoucherTotals();
    }

    function calculateVoucherTotals() {
        var totalBasic = 0;
        var totalDiscount = 0;
        var totalAmount = 0;
        var totalTax = 0;

        $('#items-group tbody tr.form-row:not(.empty-form)').each(function() {
            var $row = $(this);
            var qty = parseFloat($row.find('.field-quantity input').val()) || 0;
            var rate = parseFloat($row.find('.field-rate input').val()) || 0;
            var discount = parseFloat($row.find('.field-discount input').val()) || 0;
            var taxPercent = parseFloat($row.find('.field-tax input').val()) || 0;

            var basicAmount = qty * rate;
            var amountAfterDiscount = basicAmount - discount;
            var taxAmount = amountAfterDiscount * (taxPercent / 100);

            totalBasic += basicAmount;
            totalDiscount += discount;
            totalAmount += amountAfterDiscount;
            totalTax += taxAmount;
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
