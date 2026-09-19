(function () {
  "use strict";

  // Purely a mobile UX hint: shows the numeric keypad on phones for
  // amount/qty/rate fields. Does NOT change what is calculated,
  // validated or saved — it only sets an HTML attribute that mobile
  // browsers use to pick a keyboard layout.
  // NOTE: Quantity is deliberately left out - it now accepts "10+2"
  // style free-quantity schemes, and a decimal keypad usually hides
  // the "+" key.
  var NUMERIC_FIELD_CLASSES = [
    "field-rate",
    "field-discount",
    "field-tax",
    "field-amount",
    "field-debit",
    "field-credit",
    "field-opening",
    "field-opening_main",
    "field-opening_value",
    "field-sale_price",
    "field-purchase_price",
    "field-mrp",
    "field-conversion",
  ];

  function applyNumericHints(scope) {
    NUMERIC_FIELD_CLASSES.forEach(function (cls) {
      var inputs = scope.querySelectorAll("td." + cls + " input, .field-box." + cls + " input");
      inputs.forEach(function (el) {
        if (el.type === "text" || el.type === "number") {
          el.setAttribute("inputmode", "decimal");
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyNumericHints(document);
  });

  // Re-apply whenever Django admin adds a new inline row (Add another Item).
  if (window.django && window.django.jQuery) {
    window.django.jQuery(document).on("formset:added", function (event, $row) {
      applyNumericHints($row.get ? $row.get(0) : $row);
    });
  }
})();
