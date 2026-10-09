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

  // ---------------------------------------------------------------------------
  // Dynamic submit-row height measurement.
  //
  // On mobile the fixed .submit-row can be tall (3 stacked buttons ~160 px).
  // We measure it and write the result into the --submit-row-h CSS custom
  // property on :root.  The CSS uses that variable for:
  //   * #content padding-bottom  (last field never covered by the bar)
  //   * #erp-mobile-nav-toggle bottom  (FAB always above the save bar)
  //
  // Re-measured on resize (orientation change) and after formset mutations.
  // ---------------------------------------------------------------------------
  function updateSubmitRowHeight() {
    var row = document.querySelector(".submit-row");
    if (!row) return;
    var h = row.getBoundingClientRect().height;
    if (h > 0) {
      document.documentElement.style.setProperty("--submit-row-h", Math.ceil(h) + "px");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyNumericHints(document);

    // First measurement after layout is complete.
    updateSubmitRowHeight();

    // Re-measure on resize / orientation flip.
    window.addEventListener("resize", updateSubmitRowHeight, { passive: true });

    // Also re-measure after a short delay to catch late renders.
    setTimeout(updateSubmitRowHeight, 300);
  });

  // Re-apply whenever Django admin adds a new inline row (Add another Item).
  if (window.django && window.django.jQuery) {
    window.django.jQuery(document).on("formset:added", function (event, $row) {
      applyNumericHints($row.get ? $row.get(0) : $row);
      // Adding a row can shift page layout; re-measure after Django settles.
      setTimeout(updateSubmitRowHeight, 150);
    });
  }
})();

