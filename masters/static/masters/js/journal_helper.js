(function($) {
    'use strict';

    function num($input) {
        return parseFloat($input.val()) || 0;
    }

    function updateReadonly($container, val) {
        var formatted = val.toFixed(2);
        var $el = $container.find('.readonly');
        if ($el.length) {
            $el.text(formatted);
        } else {
            var $target = $container.find('div.readonly, p');
            if ($target.length) {
                $target.text(formatted);
            }
        }
    }

    function updateTotals() {
        var debit = 0;
        var credit = 0;
        $('#lines-group tbody tr.form-row:not(.empty-form)').each(function() {
            var $row = $(this);
            if ($row.find('.field-DELETE input').is(':checked')) {
                return;
            }
            debit += num($row.find('.field-debit input'));
            credit += num($row.find('.field-credit input'));
        });
        updateReadonly($('.field-total_debit'), debit);
        updateReadonly($('.field-total_credit'), credit);

        var diff = Math.abs(debit - credit);
        var $diffEl = $('.field-difference').find('.readonly');
        if (!$diffEl.length) {
            $diffEl = $('.field-difference').find('div.readonly, p');
        }
        if ($diffEl.length) {
            if (diff < 0.005 && (debit > 0 || credit > 0)) {
                $diffEl.html('<strong>0.00</strong> <span style="color: #2e7d32; font-weight: bold; margin-left: 8px;">✓ Balanced</span>');
            } else if (diff >= 0.005) {
                $diffEl.html('<strong>' + diff.toFixed(2) + '</strong> <span style="color: #c62828; font-weight: bold; margin-left: 8px;">⚠ Out of Balance</span>');
            } else {
                $diffEl.text('0.00');
            }
        }
    }

    $(document).on('input change keyup', '#lines-group .field-debit input', function() {
        var $row = $(this).closest('tr');
        if (num($(this)) > 0) {
            $row.find('.field-credit input').val('0.00');
        }
        updateTotals();
    });

    $(document).on('input change keyup', '#lines-group .field-credit input', function() {
        var $row = $(this).closest('tr');
        if (num($(this)) > 0) {
            $row.find('.field-debit input').val('0.00');
        }
        updateTotals();
    });

    $(document).on('change', '#lines-group .field-DELETE input', updateTotals);
    $(document).on('click', '#lines-group .inline-deletelink', function() {
        setTimeout(updateTotals, 50);
    });
    $(document).on('formset:added formset:removed', updateTotals);

    $(document).ready(updateTotals);
})(django.jQuery);
