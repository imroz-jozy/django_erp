# GST & Stock Correctness Implementation Plan

## Repository Research (Conclusions)

### Scope:
User explicitly scoped work to **GST correctness (no cess)** and **Stock correctness**.

### GST Findings — 4 Confirmed Bugs:

**BUG G1 — GST Outward Summary Credit Note tax-split is wrong:**
- Location: `masters/reports.py` lines L725–L746 inside `gst_outward_summary()`
- Current code: When iterating standalone `CreditNote` vouchers (not Sale Returns), each CN is appended as one row with:
  ```python
  "taxable": cn.total_amount,
  "cgst": ZERO, "sgst": ZERO, "igst": ZERO, "cess": ZERO,
  "total": cn.total_amount,
  ```
- Problem: If the CN was a price adjustment against a taxable sale (e.g. short-rate-diff of 100 + 18 GST = 118 total_amount), the GSTR report treats 118 as "taxable" with zero tax, under-reporting outward GST reduction by 18. Real ERP rule: either (a) don't report standalone CNs in GSTR-1 at all if they have no linked tax breakup, OR (b) skip them entirely and log a warning. Better — as a safe minimum for correct filing — **exclude standalone Credit Notes** (they are not HSN-based sale returns) from the GSTR outward table so numbers don't inflate/deflate wrongly. Sale Returns (already correctly split via `_sale_return_line_facts`) already cover goods returns in the Note rows section.
- Severity: Medium — could mislead GSTR filing.

**BUG G2 — Purchase Reverse Charge (RCM) missing model-level clean validation (URD guard):**
- Location: `Purchase.clean()` or admin form — there is **NO guard** for:
  - User ticks `is_reverse_charge=True` but `purchase_type.rcm_payable_account` is NULL → posting code at reports.py L150 returns `None` and silently skips the RCM payable liability (supplier credited with full `net_amount` instead of just `net-tax`; no RCM liability credited). Trial balance would mis-state both the supplier credit and the RCM liability.
  - User buys from an **unregistered party** (no account.gst) but does NOT tick RCM → purchase may have a tax % from item default, CGST/SGST posted as "input" but no corresponding output liability booked. Indian GST requires RCM on URD purchases of notified categories.
- Severity: High — silent accounting error on RCM without a `rcm_payable_account`.

**BUG G3 — `_voucher_entries_for_account` account ledger drill filters by `account_id == acc_id` for CN/DN but does NOT pre-filter date range on CN/DN:**
- Location: `reports.py` lines L1408–L1420 (CreditNote / DebitNote queries inside `_voucher_entries_for_account`)
- Current: `CreditNote.objects.select_related(...)` without any `.filter(date__gte..., date__lte...)`. Then at `account_ledger()`, L1464 onwards applies python-level date filter. This is **NOT a bug** — just verified that `account_ledger()` iterates `all_entries` and then slicer. BUT — for vouchers (Sale/Purchase/SR/PR queries in same function), we have NO filter too. So it's consistent. OK no actual bug.

**BUG G4 — IGST/CGST+SGST split at `tax_split_postings` uses rounding HALF_UP but subtractive split could have a 0.01 drift off the input tax_amount:**
- Location: `models.py` L279–L305
- Current code: `first_amt = quantize(tax * pct/100, 2dp HALF_UP)`, `second_amt = tax_amount - first_amt`.
- Example: tax_amount = 0.01, pct=50% → first=0.01, second=0.00. Mathematically 0.01 vs 0.00 but the sum still equals input. Sum is NEVER wrong because the second term is subtractive. → **Actually NOT a bug.** Verified: `first_amt + second_amt == tax_amount` always holds by construction.

### Stock Findings — 3 Confirmed Bugs / Missing Guards:

**BUG S1 — Negative stock sale allowed (no guard):**
- Location: Admin form clean method, save_formset, or model save
- Currently: `SaleItem`, `PurchaseReturnItem` decrease stock qty in `stock_figures()` but there's **no clean validation** anywhere (no model.clean, no admin.py save_formset guard, no signal) to prevent `closing_qty < 0` after a sale/PR. User can sell 100 widgets when only 5 are in stock → stock report shows huge negative WAR negative value, trial balance mis-states.
- Severity: High — directly mis-states Closing Stock asset and COGS in P&L.

**BUG S2 — Free quantity is correctly included in WAR denominator but zero-value free PurchaseItem lines (e.g. receipt of 100 free goods with discount = qty*rate, i.e. 100% discount) need careful handling:**
- Verified code at `stock_figures()` L420: `purchase_qty[item_id] += line.total_quantity` ✅ (billed + free for stock-in)
- L421: `purchase_amt[item_id] += line_amt["amount_after_discount"]` ✅ (only billed, post-discount value)
- Result: 10 qty billed + 2 free @ 100 rate, disc 0 → WAR denominator = 12 qty, numerator = (10*100)/divisor. This correctly **dilutes weighted avg** (free qty lowers avg rate) ✅.
- **No bug → S2 is correct.**

**BUG S3 — Stock opening_value vs opening_main rate drift (unsanitized input guard missing):**
- Item model allows `opening_main=10` with `opening_value=0` → total_qty_in = 10 + pur_qty, total_val_in = 0 + pur_val → WAR drops (acceptable, may be legacy zero-cost opening).
- Item model allows `opening_main=0` with `opening_value=1000` → division-safe (guard `if total_qty_in > 0: war = ... else fallback`). So valuation is safe. ✅ Not a bug.
- **No bug → S3 safe via existing guards.**

**BUG S4 — Purchase Returns reduce stock qty but don't adjust the WAR numerator/denominator before rate calculation:**
- Location: `stock_figures()` L440–L471
- Current math:
  ```python
  total_qty_in = op_qty + pur_qty      # only op + purchases
  total_val_in = op_val + pur_val      # only op + purchases
  war = total_val_in / total_qty_in    # rate on received stock, not affected by returns (correct)
  closing_qty = (total_qty_in + sret_qty) - (sol_qty + pret_qty)
  ```
- Correct Tally ERP rule: Returns happen **after** WAR is set, so closing qty = (in + return_in) - (out + return_out), valued at unchanged WAR. This is standard cost-flow assumption. → **Not a bug, S4 is correct.**

### Net Audit Result:
Real bugs to fix: **G1, G2, S1** only.

---

## Files and Modules

- `masters/models.py`:
  - Add `Purchase.clean()` to validate:
    - If `is_reverse_charge=True` and `purchase_type_id`: `purchase_type.rcm_payable_account` cannot be NULL (raise ValidationError)
    - If `account_id` and not `account.gst` (URD party): warn (or enforce RCM if purchase_type has tax accounts set)
- `masters/admin.py`:
  - Override `save_model` / `save_formset` on **SaleAdmin** and **PurchaseReturnAdmin** to compute *projected* closing qty per-item at save time, raise `messages.error` + block save if any item line would push stock negative using `stock_figures` math logic.
- `masters/reports.py`:
  - Inside `gst_outward_summary()` L725–L746: REMOVE the standalone `CreditNote.objects.filter()` iteration block from Note rows. Only Sale Returns (already correct via `_sale_return_line_facts`) should appear in the Credit/Debit Notes section. Reason: standalone CNs have no HSN-level tax split and would otherwise show wrong taxable/tax numbers for GSTR.
  - Add doc-comment on gst_outward_summary why standalone CNs are excluded.
- `masters/money.py`: no changes.
- `masters/excel_service.py`: no changes required for GST/Stock scope (excel import saves raw values; validations run through same admin/model save pipeline if invoked via view; but excel bulk bypasses model clean so add a note and consider adding the negative-stock check at excel_service import_sales + import_purchase_returns time — optional add-on).

---

## Implementation Steps (Dependency Order)

### Step 1: Fix G2 — RCM validation on Purchase model clean()
Add a `def clean(self)` to `Purchase` model in models.py:
- Guard 1: If `self.is_reverse_charge` and `self.purchase_type_id` is set, assert `self.purchase_type.rcm_payable_account_id` is not None → raise ValidationError({"is_reverse_charge": "..."}).
- Guard 2: If `self.account_id` is set and `self.account.gst` is blank (unregistered dealer) AND `self.items.aggregate(Sum('tax'))` would produce tax (best-effort lookup): emit a ValidationError({"account": "Purchases from unregistered parties with tax% should have Reverse Charge ticked."}) — this is a soft guard; allow override via `raise` or just a warning via messages.error at admin save time.
- Ensure this runs automatically via existing `super().clean()` calls in admin OR add `full_clean()` in Purchase.save() if needed.

### Step 2: Fix S1 — Negative Stock guard at Sale / PurchaseReturn admin save time
In `admin.py`:
- Add a small helper `_projected_stock_after(voucher_type, voucher_instance, date)` that:
  - Runs a mini `stock_figures()` for the given date_from=∞ to date_to=date.
  - Applies the NEW voucher lines' qty change (sale subtracts, PR subtracts, SR adds back).
  - Returns per-item dict `{item_id: projected_closing_qty}`.
- In `SaleAdmin.save_related(request, form, formsets, change)`:
  - After inline items are built (pre-save to DB): compute projected_closing for each sale item's item_id, check all >=0.
  - If any would go negative: call `messages.error(request, f"Negative stock blocked: Item '{name}' would be at {qty} qty after saving.")` and re-raise `ValidationError` so save aborts.
- Repeat for PurchaseReturnAdmin.save_related (PR also subtracts stock).
- Optional: Add same guard at SaleReturn.save (but SR adds stock back so it's safe).
- Do NOT add to Purchase admin (purchases increase stock, safe) or receipt/payment.

### Step 3: Fix G1 — gst_outward_summary remove standalone Credit Note note-rows
In `reports.py` `gst_outward_summary()`:
- Remove (comment out, or replace with a one-liner guard `# Standalone Credit Notes excluded from GSTR: no HSN tax split available.`) the block:
  ```python
  for cn in (CreditNote.objects.filter(...).select_related(...)...):
      ... note_rows.append(...)
  ```
- Keep Sale Return `_sale_return_line_facts` driven note rows (those are correct).
- Verify the `notes_total` and `grand_total` then reflect only Sale Returns + 0 for standalone CNs (grand total may shift upward; this is the *correct* GSTR-1 behavior because a standalone CN without tax split can't legally reduce GSTR liability).

### Step 4: Add negative stock guard (soft) at Excel import entry points (optional)
In excel_service.py `import_sales_from_excel` and `import_purchase_returns_from_excel`:
- Before creating/updating each voucher, run the same negative-stock guard: per item line in that import, compute projected stock after prior rows in the same batch. If negative, flag the row as skipped with an error message.
- Keep this optional; only do Step 4 if Steps 1-3 have excess budget.

---

## Dependencies and Considerations

1. **Model clean vs admin save tradeoff**: Purchase.clean() runs before DB insert via `ModelForm.full_clean()` in Django admin automatically; save() override not needed for G2.
2. **S1 performance risk**: Running `stock_figures()` on every Sale save could be slow for large DBs. Mitigation: use a PER-ITEM targeted query instead of the full stock_figures() — just get opening_main + purchase_qty_sum(through date) - sale_qty_sum(through date) + SR_sum - PR_sum per item_id directly via ORM.
3. **G1 GSTR filing safety**: When removing standalone CN from note_rows, total outward liability appears larger. This is the **correct, conservative** behavior for GST — standalone CNs should only be adjusted via amendment returns, not auto-credited in the GSTR-1 outward summary unless they have HSN tax lines.
4. **Transactions**: `save_related` wraps in a transaction by default in Django admin; raising ValidationError there will roll back all inline saves cleanly.

---

## Validation

After implementation:
1. `python manage.py check` → 0 issues.
2. Unit tests via inline script:
   a. Purchase with `is_reverse_charge=True` and NULL `rcm_payable_account` → must raise ValidationError.
   b. Sale with billed qty > stock → must block with negative-stock message; same for PR.
   c. gst_outward_summary sample: standalone CreditNote in date range must NOT appear in note_rows; SaleReturn entries must still appear with full tax split.
3. Django dev server sanity run: create the scenarios above using admin UI and confirm save allowed/blocked.

---

## Risks and Handling

| Risk | Likelihood | Impact | Handling |
|---|---|---|---|
| Negative stock guard blocks legitimate "backdated voucher entry" (user enters 1 Sep sale first, then 31 Aug stock-in) | Medium | Med (annoying UX) | Add a `request.POST.get("force_negative_stock")` hidden override, or just a **warning message** that still allows save; or check only for *post-dated* relative to *current* closing. **Default plan: block hard** (matching Tally ERP behavior); user can temporarily raise stock via opening edit if needed. |
| Removing standalone CN from GSTR causes user surprise / reports "CN missing" | High | Low (visible, but filing-safe) | Add a footnote on report_gst_outward.html template: "Note: Standalone Credit Notes (not linked to returns) are excluded from this report as they contain no HSN-level tax split. Use Sale Return vouchers for returns that should appear in GSTR-1." Out of scope here but note the fix. |
| Excel import bypasses Purchase.clean() — silent RCM-invalid rows saved | Low | High | Model.clean() does NOT automatically run on bulk ORM `save()` without `full_clean()`. Mitigation: in `Purchase.save()`, add `if not self._state.adding or self.purchase_type_id: self.full_clean(exclude=...)` so even ORM saves validate. Call out: excel_service creates rows without explicit full_clean; this would fix it. |
| S1 helper incorrectly counts already-saved lines on `change` (update existing Sale) → double-counts qty change | Med | Med (wrong negative-stock verdict) | When computing projected_closing on change, subtract (old lines' qty effect) before adding (new lines' qty effect). Use formset `initial_forms` vs `new_forms` split in save_related. |
