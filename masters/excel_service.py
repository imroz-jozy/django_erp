import io
import re
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.http import HttpResponse

# Try importing openpyxl; handled gracefully if not yet installed
try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


def check_openpyxl():
    """Raise or return error message if openpyxl is not installed."""
    if not OPENPYXL_AVAILABLE:
        raise ImportError(
            "The 'openpyxl' module is required for Excel import/export. "
            "Please run: pip install openpyxl"
        )


def _apply_header_style(ws, headers, bg_color="1F497D", text_color="FFFFFF"):
    """Format the header row of an openpyxl worksheet."""
    header_font = Font(name="Calibri", size=11, bold=True, color=text_color)
    header_fill = PatternFill(start_color=bg_color, end_color=bg_color, fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC"),
    )

    ws.row_dimensions[1].height = 28
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border


def _auto_adjust_columns(ws, min_width=15, max_width=35):
    """Auto-adjust worksheet column widths based on cell content."""
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        adjusted = max(max_len + 4, min_width)
        ws.column_dimensions[col_letter].width = min(adjusted, max_width)


# ==============================================================================
# ITEM TEMPLATE & IMPORT
# ==============================================================================

ITEM_HEADERS = [
    "Item Name *",
    "Item Group",
    "Main Unit *",
    "Alt Unit",
    "Conversion Factor",
    "HSN Code",
    "Tax Rate %",
    "Sale Price",
    "Purchase Price",
    "MRP",
    "Opening Qty",
    "Opening Value",
]

ITEM_SAMPLE_DATA = [
    [
        "Laptop Dell Inspiron 15",
        "Electronics",
        "PCS",
        "",
        1,
        "84713010",
        18,
        55000.00,
        48000.00,
        60000.00,
        10,
        480000.00,
    ],
    [
        "Cotton T-Shirt Blue M",
        "Garments",
        "PCS",
        "BOX",
        10,
        "61091000",
        5,
        499.00,
        320.00,
        699.00,
        50,
        16000.00,
    ],
    [
        "Basmati Rice Royal 25kg",
        "Groceries",
        "BAG",
        "KG",
        25,
        "10063020",
        0,
        2200.00,
        1950.00,
        2400.00,
        20,
        39000.00,
    ],
]


def generate_item_template():
    """Generate and return an in-memory .xlsx file for Item master import."""
    check_openpyxl()
    from .models import Unit

    wb = openpyxl.Workbook()
    
    # Sheet 1: Items Template
    ws = wb.active
    ws.title = "Items Template"
    _apply_header_style(ws, ITEM_HEADERS, bg_color="1F497D")

    # Add sample rows
    for row_data in ITEM_SAMPLE_DATA:
        ws.append(row_data)

    _auto_adjust_columns(ws)

    # Sheet 2: Available Units Reference
    ws_units = wb.create_sheet(title="Existing Units Reference")
    ws_units.append(["Unit Name", "Print Name", "Decimal Places"])
    _apply_header_style(ws_units, ["Unit Name", "Print Name", "Decimal Places"], bg_color="4F81BD")

    units = Unit.objects.all().order_by("name")
    if units.exists():
        for u in units:
            ws_units.append([u.name, u.print_name, u.decimal_places])
    else:
        ws_units.append(["PCS", "PCS", 2])
        ws_units.append(["KGS", "KGS", 2])
        ws_units.append(["MTR", "MTR", 2])
        ws_units.append(["BOX", "BOX", 0])

    _auto_adjust_columns(ws_units)

    # Save to buffer
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def _parse_decimal(val, default=Decimal("0")):
    if val is None or val == "":
        return default
    if isinstance(val, (int, float, Decimal)):
        try:
            return Decimal(str(val))
        except InvalidOperation:
            return default
    cleaned = re.sub(r"[^\d.-]", "", str(val).strip())
    if not cleaned:
        return default
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return default


def _clean_str(val):
    if val is None:
        return ""
    return str(val).strip()


def _normalize_header(header):
    if not header:
        return ""
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", str(header).lower())
    return cleaned


def import_items_from_excel(file_obj, update_existing=False):
    """
    Parse an Excel file and import Items into the database.
    Returns dict with counts and error list.
    """
    check_openpyxl()
    from .models import Item, Unit

    result = {
        "success": False,
        "total_rows": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
    }

    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
        ws = wb.active
    except Exception as e:
        result["errors"].append(f"Could not open Excel file: {str(e)}")
        return result

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        result["errors"].append("The Excel file is empty.")
        return result

    header_row = rows[0]
    header_map = {}
    for idx, cell in enumerate(header_row):
        norm = _normalize_header(cell)
        if norm:
            header_map[norm] = idx

    def get_val(row, *aliases):
        for alias in aliases:
            norm = _normalize_header(alias)
            if norm in header_map:
                col_idx = header_map[norm]
                if col_idx < len(row):
                    return row[col_idx]
        return None

    has_item_col = any(
        _normalize_header(a) in header_map
        for a in ["Item Name", "Item", "Name", "item_name"]
    )
    if not has_item_col:
        result["errors"].append(
            "Missing required column 'Item Name' in the header row."
        )
        return result

    unit_cache = {u.name.lower(): u for u in Unit.objects.all()}

    def get_or_create_unit(name_str):
        name_str = _clean_str(name_str)
        if not name_str:
            return None
        lower = name_str.lower()
        if lower in unit_cache:
            return unit_cache[lower]
        unit, _ = Unit.objects.get_or_create(
            name=name_str.upper(),
            defaults={"print_name": name_str.upper(), "decimal_places": 2},
        )
        unit_cache[lower] = unit
        unit_cache[unit.name.lower()] = unit
        return unit

    data_rows = rows[1:]
    items_to_save = []

    for row_idx, row in enumerate(data_rows, start=2):
        if not any(row):
            continue

        result["total_rows"] += 1

        name = _clean_str(get_val(row, "Item Name *", "Item Name", "Item", "item_name"))
        if not name:
            result["errors"].append(f"Row {row_idx}: 'Item Name' is required.")
            continue

        item_group = _clean_str(get_val(row, "Item Group", "Group", "item_group"))
        
        main_unit_str = _clean_str(get_val(row, "Main Unit *", "Main Unit", "Unit", "main_unit"))
        if not main_unit_str:
            main_unit_str = "PCS"
        main_unit = get_or_create_unit(main_unit_str)

        alt_unit_str = _clean_str(get_val(row, "Alt Unit", "alt_unit"))
        alt_unit = get_or_create_unit(alt_unit_str) if alt_unit_str else None

        conversion = _parse_decimal(get_val(row, "Conversion Factor", "Conversion", "conversion"), Decimal("1"))
        if conversion <= 0:
            conversion = Decimal("1")

        hsn = _clean_str(get_val(row, "HSN Code", "HSN", "hsn"))
        hsn = re.sub(r"\D", "", hsn)

        tax = _parse_decimal(get_val(row, "Tax Rate %", "Tax Rate", "Tax", "tax"), Decimal("0"))
        sale_price = _parse_decimal(get_val(row, "Sale Price", "sale_price"), Decimal("0"))
        purchase_price = _parse_decimal(get_val(row, "Purchase Price", "purchase_price"), Decimal("0"))
        mrp = _parse_decimal(get_val(row, "MRP", "mrp"), Decimal("0"))
        opening_main = _parse_decimal(get_val(row, "Opening Qty", "Opening Main", "opening_main"), Decimal("0"))
        opening_value = _parse_decimal(get_val(row, "Opening Value", "opening_value"), Decimal("0"))

        items_to_save.append({
            "row_idx": row_idx,
            "item_name": name,
            "item_group": item_group,
            "main_unit": main_unit,
            "alt_unit": alt_unit,
            "conversion": conversion,
            "hsn": hsn,
            "tax": tax,
            "sale_price": sale_price,
            "purchase_price": purchase_price,
            "mrp": mrp,
            "opening_main": opening_main,
            "opening_value": opening_value,
        })

    with transaction.atomic():
        for itm in items_to_save:
            row_idx = itm["row_idx"]
            existing = Item.objects.filter(item_name__iexact=itm["item_name"]).first()
            if existing:
                if update_existing:
                    existing.item_group = itm["item_group"]
                    existing.main_unit = itm["main_unit"]
                    existing.alt_unit = itm["alt_unit"]
                    existing.conversion = itm["conversion"]
                    existing.hsn = itm["hsn"]
                    existing.tax = itm["tax"]
                    existing.sale_price = itm["sale_price"]
                    existing.purchase_price = itm["purchase_price"]
                    existing.mrp = itm["mrp"]
                    existing.opening_main = itm["opening_main"]
                    existing.opening_value = itm["opening_value"]
                    try:
                        existing.full_clean()
                        existing.save()
                        result["updated"] += 1
                    except Exception as err:
                        result["errors"].append(f"Row {row_idx} ({itm['item_name']}): {str(err)}")
                else:
                    result["skipped"] += 1
            else:
                new_item = Item(
                    item_name=itm["item_name"],
                    item_group=itm["item_group"],
                    main_unit=itm["main_unit"],
                    alt_unit=itm["alt_unit"],
                    conversion=itm["conversion"],
                    hsn=itm["hsn"],
                    tax=itm["tax"],
                    sale_price=itm["sale_price"],
                    purchase_price=itm["purchase_price"],
                    mrp=itm["mrp"],
                    opening_main=itm["opening_main"],
                    opening_value=itm["opening_value"],
                )
                try:
                    new_item.full_clean()
                    new_item.save()
                    result["created"] += 1
                except Exception as err:
                    result["errors"].append(f"Row {row_idx} ({itm['item_name']}): {str(err)}")

    result["success"] = (result["created"] > 0 or result["updated"] > 0 or (result["skipped"] > 0 and not result["errors"]))
    return result


# ==============================================================================
# ACCOUNT TEMPLATE & IMPORT
# ==============================================================================

ACCOUNT_HEADERS = [
    "Account Name *",
    "Account Group *",
    "Opening Balance",
    "Opening Type (DR/CR)",
    "Address",
    "State",
    "GSTIN",
    "Is Registered (Yes/No)",
    "Mobile No",
]

ACCOUNT_SAMPLE_DATA = [
    [
        "Apex Infotech Pvt Ltd",
        "Sundry Debtors",
        25000.00,
        "DR",
        "Plot 42, Electronic City Phase 1",
        "Karnataka",
        "29AAAAA0000A1Z5",
        "Yes",
        "9845012345",
    ],
    [
        "National Steel Corporation",
        "Sundry Creditors",
        45000.00,
        "CR",
        "Shop 12, Industrial Area, Sector 5",
        "Maharashtra",
        "27BBBBB1111B1Z2",
        "Yes",
        "9822098765",
    ],
    [
        "HDFC Bank Current A/c 50200",
        "Bank Accounts",
        150000.00,
        "DR",
        "MG Road Branch",
        "Delhi",
        "",
        "No",
        "",
    ],
]


def generate_account_template():
    """Generate and return an in-memory .xlsx file for Account master import."""
    check_openpyxl()
    from .models import AccountGroup

    wb = openpyxl.Workbook()

    # Sheet 1: Accounts Template
    ws = wb.active
    ws.title = "Accounts Template"
    _apply_header_style(ws, ACCOUNT_HEADERS, bg_color="2C5E3B")

    # Add sample rows
    for row_data in ACCOUNT_SAMPLE_DATA:
        ws.append(row_data)

    _auto_adjust_columns(ws)

    # Sheet 2: Available Account Groups Reference
    ws_groups = wb.create_sheet(title="Available Account Groups")
    ws_groups.append(["Group Name", "Nature", "Primary Group"])
    _apply_header_style(ws_groups, ["Group Name", "Nature", "Primary Group"], bg_color="558B2F")

    groups = AccountGroup.objects.all().order_by("name")
    for g in groups:
        ws_groups.append([g.name, g.get_nature_display(), "Yes" if g.primary_group else "No"])

    _auto_adjust_columns(ws_groups)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def import_accounts_from_excel(file_obj, update_existing=False):
    """
    Parse an Excel file and import Accounts into the database.
    Returns dict with counts and error list.
    """
    check_openpyxl()
    from .models import Account, AccountGroup, DEFAULT_ACCOUNTS

    result = {
        "success": False,
        "total_rows": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
    }

    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
        ws = wb.active
    except Exception as e:
        result["errors"].append(f"Could not open Excel file: {str(e)}")
        return result

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        result["errors"].append("The Excel file is empty.")
        return result

    header_row = rows[0]
    header_map = {}
    for idx, cell in enumerate(header_row):
        norm = _normalize_header(cell)
        if norm:
            header_map[norm] = idx

    def get_val(row, *aliases):
        for alias in aliases:
            norm = _normalize_header(alias)
            if norm in header_map:
                col_idx = header_map[norm]
                if col_idx < len(row):
                    return row[col_idx]
        return None

    has_acc_col = any(
        _normalize_header(a) in header_map
        for a in ["Account Name", "Account", "Name", "account_name"]
    )
    if not has_acc_col:
        result["errors"].append(
            "Missing required column 'Account Name' in the header row."
        )
        return result

    group_cache = {g.name.lower(): g for g in AccountGroup.objects.all()}
    predefined_account_names = {name.lower() for name, *_ in DEFAULT_ACCOUNTS}

    data_rows = rows[1:]
    accounts_to_save = []

    for row_idx, row in enumerate(data_rows, start=2):
        if not any(row):
            continue

        result["total_rows"] += 1

        name = _clean_str(get_val(row, "Account Name *", "Account Name", "Account", "Name", "account_name"))
        if not name:
            result["errors"].append(f"Row {row_idx}: 'Account Name' is required.")
            continue

        grp_str = _clean_str(get_val(row, "Account Group *", "Account Group", "Group", "account_group"))
        if not grp_str:
            result["errors"].append(f"Row {row_idx} ({name}): 'Account Group' is required.")
            continue

        group_obj = group_cache.get(grp_str.lower())
        if not group_obj:
            matched = [g for g_name, g in group_cache.items() if grp_str.lower() in g_name]
            if matched:
                group_obj = matched[0]
            else:
                result["errors"].append(
                    f"Row {row_idx} ({name}): Account Group '{grp_str}' does not exist. "
                    f"Please choose a valid group (e.g., Sundry Debtors, Sundry Creditors)."
                )
                continue

        opening = _parse_decimal(get_val(row, "Opening Balance", "Opening", "opening"), Decimal("0"))
        
        op_type_raw = _clean_str(get_val(row, "Opening Type (DR/CR)", "Opening Type", "opening_type")).upper()
        if "CR" in op_type_raw or "CREDIT" in op_type_raw:
            opening_type = Account.OpeningType.CR
        else:
            opening_type = Account.OpeningType.DR

        address = _clean_str(get_val(row, "Address", "address"))
        state = _clean_str(get_val(row, "State", "state"))
        gst = _clean_str(get_val(row, "GSTIN", "GST", "gst"))

        reg_raw = _clean_str(get_val(row, "Is Registered (Yes/No)", "Is Registered", "Registered", "is_registered")).lower()
        is_registered = reg_raw in ["yes", "y", "true", "1"] or bool(gst)

        mobile_no = _clean_str(get_val(row, "Mobile No", "Mobile", "mobile_no"))

        accounts_to_save.append({
            "row_idx": row_idx,
            "account_name": name,
            "account_group": group_obj,
            "opening": opening,
            "opening_type": opening_type,
            "address": address,
            "state": state,
            "gst": gst,
            "is_registered": is_registered,
            "mobile_no": mobile_no,
        })

    with transaction.atomic():
        for acc in accounts_to_save:
            row_idx = acc["row_idx"]
            existing = Account.objects.filter(account_name__iexact=acc["account_name"]).first()
            if existing:
                # Built-in ERP accounts are protected from Excel updates.
                if existing.account_name.lower() in predefined_account_names:
                    result["skipped"] += 1
                elif update_existing:
                    existing.account_group = acc["account_group"]
                    existing.opening = acc["opening"]
                    existing.opening_type = acc["opening_type"]
                    existing.address = acc["address"]
                    existing.state = acc["state"]
                    existing.gst = acc["gst"]
                    existing.is_registered = acc["is_registered"]
                    existing.mobile_no = acc["mobile_no"]
                    try:
                        existing.full_clean()
                        existing.save()
                        result["updated"] += 1
                    except Exception as err:
                        result["errors"].append(f"Row {row_idx} ({acc['account_name']}): {str(err)}")
                else:
                    result["skipped"] += 1
            else:
                new_acc = Account(
                    account_name=acc["account_name"],
                    account_group=acc["account_group"],
                    opening=acc["opening"],
                    opening_type=acc["opening_type"],
                    address=acc["address"],
                    state=acc["state"],
                    gst=acc["gst"],
                    is_registered=acc["is_registered"],
                    mobile_no=acc["mobile_no"],
                )
                try:
                    new_acc.full_clean()
                    new_acc.save()
                    result["created"] += 1
                except Exception as err:
                    result["errors"].append(f"Row {row_idx} ({acc['account_name']}): {str(err)}")

    result["success"] = (result["created"] > 0 or result["updated"] > 0 or (result["skipped"] > 0 and not result["errors"]))
    return result


# ==============================================================================
# ACCOUNT GROUP TEMPLATE & IMPORT
# ==============================================================================

ACCOUNT_GROUP_HEADERS = ["Group Name *", "Primary (Y/N) *", "Parent Group", "Nature"]

ACCOUNT_GROUP_SAMPLE_DATA = [
    ["Current Assets", "Y", "", "Asset"],
    ["Bank Accounts", "N", "Current Assets", ""],
    ["Cash-in-hand", "N", "Current Assets", ""],
    ["Sundry Debtors", "N", "Current Assets", ""],
    ["Revenue Accounts", "Y", "", "Income"],
    ["Sale", "N", "Revenue Accounts", ""],
]


def generate_account_group_template():
    """Generate an Excel template for primary and secondary account groups."""
    check_openpyxl()
    from .models import AccountGroup

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Account Groups"
    _apply_header_style(sheet, ACCOUNT_GROUP_HEADERS, bg_color="5B9BD5")
    for row in ACCOUNT_GROUP_SAMPLE_DATA:
        sheet.append(row)
    _auto_adjust_columns(sheet)

    reference = workbook.create_sheet(title="Existing Account Groups")
    _apply_header_style(reference, ["Group Name", "Primary (Y/N)", "Parent Group", "Nature"], bg_color="366092")
    for group in AccountGroup.objects.select_related("under_group").order_by("name")[:500]:
        reference.append([
            group.name,
            "Y" if group.primary_group else "N",
            group.under_group.name if group.under_group else "",
            group.get_nature_display(),
        ])
    _auto_adjust_columns(reference)

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def import_account_groups_from_excel(file_obj, update_existing=False):
    """Import account groups; secondary groups always inherit the parent's nature."""
    check_openpyxl()
    from .models import AccountGroup, DEFAULT_GROUPS

    result = {"success": False, "total_rows": 0, "created": 0, "updated": 0, "skipped": 0, "errors": []}
    try:
        workbook = openpyxl.load_workbook(file_obj, data_only=True)
        rows = list(workbook.active.iter_rows(values_only=True))
    except Exception as exc:
        result["errors"].append(f"Could not open Excel file: {str(exc)}")
        return result
    if not rows:
        result["errors"].append("The Excel file is empty.")
        return result

    header_map = {_normalize_header(cell): index for index, cell in enumerate(rows[0]) if _normalize_header(cell)}

    def value(row, *aliases):
        for alias in aliases:
            index = header_map.get(_normalize_header(alias))
            if index is not None and index < len(row):
                return row[index]
        return None

    if _normalize_header("Group Name") not in header_map:
        result["errors"].append("Missing required column 'Group Name' in the header row.")
        return result

    nature_map = {label.lower(): code for code, label in AccountGroup.Nature.choices}
    nature_map.update({code.lower(): code for code, _ in AccountGroup.Nature.choices})
    pending, seen_names = [], set()
    for row_number, row in enumerate(rows[1:], start=2):
        if not any(row):
            continue
        result["total_rows"] += 1
        name = _clean_str(value(row, "Group Name *", "Group Name", "Name"))
        group_type = _clean_str(value(row, "Primary (Y/N) *", "Primary (Y/N)", "Primary Group", "Group Type", "Type")).lower()
        parent_name = _clean_str(value(row, "Parent Group", "Under Group", "Parent"))
        nature_text = _clean_str(value(row, "Nature")).lower()
        if not name:
            result["errors"].append(f"Row {row_number}: Group Name is required.")
            continue
        if name.lower() in seen_names:
            result["errors"].append(f"Row {row_number}: Group '{name}' appears more than once in this file.")
            continue
        seen_names.add(name.lower())
        is_primary = group_type in ("primary", "yes", "y", "true", "1")
        is_secondary = group_type in ("secondary", "no", "n", "false", "0")
        if not (is_primary or is_secondary):
            result["errors"].append(f"Row {row_number} ({name}): Primary (Y/N) must be Y for Primary or N for Secondary.")
            continue
        if is_primary and parent_name:
            result["errors"].append(f"Row {row_number} ({name}): a Primary group cannot have a Parent Group.")
            continue
        if is_secondary and not parent_name:
            result["errors"].append(f"Row {row_number} ({name}): a Secondary group needs a Parent Group.")
            continue
        nature = nature_map.get(nature_text)
        if is_primary and not nature:
            result["errors"].append(f"Row {row_number} ({name}): Primary groups need Nature: Asset, Liability, Income, Expense, or Equity.")
            continue
        if is_secondary and nature_text and not nature:
            result["errors"].append(f"Row {row_number} ({name}): Nature is not valid.")
            continue
        pending.append({"row": row_number, "name": name, "primary": is_primary, "parent_name": parent_name, "nature": nature})

    if result["errors"]:
        return result

    group_cache = {group.name.lower(): group for group in AccountGroup.objects.select_related("under_group").all()}
    predefined_group_names = {name.lower() for name, *_ in DEFAULT_GROUPS}
    with transaction.atomic():
        unresolved = pending[:]
        while unresolved:
            remaining, progress = [], False
            for data in unresolved:
                parent = None
                if not data["primary"]:
                    parent = group_cache.get(data["parent_name"].lower())
                    if not parent:
                        remaining.append(data)
                        continue
                    if parent.name.lower() == data["name"].lower():
                        result["errors"].append(f"Row {data['row']} ({data['name']}): a group cannot be its own parent.")
                        continue
                existing = group_cache.get(data["name"].lower())
                # Built-in ERP groups define the accounting structure. Never
                # modify them through Excel, even when update is selected.
                if existing and existing.name.lower() in predefined_group_names:
                    result["skipped"] += 1
                elif existing and not update_existing:
                    result["skipped"] += 1
                elif existing:
                    existing.primary_group = data["primary"]
                    existing.under_group = parent
                    existing.nature = data["nature"] if data["primary"] else parent.nature
                    existing.save()
                    result["updated"] += 1
                else:
                    existing = AccountGroup.objects.create(
                        name=data["name"],
                        primary_group=data["primary"],
                        under_group=parent,
                        nature=data["nature"] if data["primary"] else parent.nature,
                    )
                    group_cache[data["name"].lower()] = existing
                    result["created"] += 1
                progress = True
            if result["errors"]:
                transaction.set_rollback(True)
                break
            if not progress:
                for data in remaining:
                    result["errors"].append(f"Row {data['row']} ({data['name']}): Parent Group '{data['parent_name']}' does not exist in the file or database, or groups form a cycle.")
                transaction.set_rollback(True)
                break
            unresolved = remaining

    if not result["errors"]:
        result["success"] = bool(result["created"] or result["updated"] or result["skipped"])
    return result


def excel_download_response(file_buffer, filename):
    """Return an HTTP response triggering an Excel file download in browser."""
    response = HttpResponse(
        file_buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ==============================================================================
# VOUCHER DATE HELPER
# ==============================================================================

import datetime


def _parse_date(val):
    """Parse various date formats from Excel (datetime, date, serial or string)."""
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    if isinstance(val, (int, float)):
        try:
            return datetime.date(1899, 12, 30) + datetime.timedelta(days=int(val))
        except Exception:
            pass
    val_str = str(val).strip()
    if not val_str:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(val_str, fmt).date()
        except ValueError:
            continue
    return None


# ==============================================================================
# SALE VOUCHER TEMPLATE & IMPORT
# ==============================================================================

SALE_VOUCHER_HEADERS = [
    "Date *",
    "Invoice No *",
    "Party (Customer) *",
    "Sale Type",
    "Item Name *",
    "Unit",
    "Quantity *",
    "Rate",
    "Discount",
    "Tax Rate %",
    "Bill Sundry 1",
    "Sundry Amount 1",
    "Bill Sundry 2",
    "Sundry Amount 2",
    "Bill Sundry 3",
    "Sundry Amount 3",
    "Narration",
]

SALE_SAMPLE_ROWS = [
    [
        "2026-09-01",
        "INV-001",
        "Apex Infotech Pvt Ltd",
        "Local Sale",
        "Laptop Dell Inspiron 15",
        "PCS",
        2,
        55000.00,
        0.00,
        18,
        "Freight & Forwarding Charges",
        500.00,
        "Rounded Off",
        0.00,
        "",
        0.00,
        "Goods delivered to Electronic City",
    ],
    [
        "2026-09-01",
        "INV-001",
        "Apex Infotech Pvt Ltd",
        "Local Sale",
        "Cotton T-Shirt Blue M",
        "PCS",
        5,
        499.00,
        50.00,
        5,
        "",
        0.00,
        "",
        0.00,
        "",
        0.00,
        "",
    ],
    [
        "2026-09-02",
        "INV-002",
        "Apex Infotech Pvt Ltd",
        "Local Sale",
        "Basmati Rice Royal 25kg",
        "BAG",
        10,
        2200.00,
        0.00,
        0,
        "Rounded Off",
        0.00,
        "",
        0.00,
        "",
        0.00,
        "Single sundry on overall bill",
    ],
]


def generate_sale_template():
    """Generate and return an in-memory .xlsx template for Sale voucher import."""
    check_openpyxl()
    from .models import Account, Item, SaleType, BillSundry

    wb = openpyxl.Workbook()

    # Sheet 1: Sale Invoices Template
    ws = wb.active
    ws.title = "Sales Invoices"
    _apply_header_style(ws, SALE_VOUCHER_HEADERS, bg_color="1F497D")
    for r in SALE_SAMPLE_ROWS:
        ws.append(r)
    _auto_adjust_columns(ws)

    # Sheet 2: Existing Accounts Reference
    ws_acc = wb.create_sheet(title="Existing Customers & Accounts")
    ws_acc.append(["Account Name", "Group", "State", "GSTIN"])
    _apply_header_style(ws_acc, ["Account Name", "Group", "State", "GSTIN"], bg_color="366092")
    for acc in Account.objects.select_related("account_group").order_by("account_name")[:200]:
        ws_acc.append([acc.account_name, acc.account_group.name if acc.account_group else "", acc.state, acc.gst])
    _auto_adjust_columns(ws_acc)

    # Sheet 3: Existing Items Reference
    ws_items = wb.create_sheet(title="Existing Items")
    ws_items.append(["Item Name", "Main Unit", "Sale Price", "Tax Rate %"])
    _apply_header_style(ws_items, ["Item Name", "Main Unit", "Sale Price", "Tax Rate %"], bg_color="4F81BD")
    for itm in Item.objects.select_related("main_unit").order_by("item_name")[:200]:
        ws_items.append([itm.item_name, itm.main_unit.name if itm.main_unit else "", float(itm.sale_price), float(itm.tax)])
    _auto_adjust_columns(ws_items)

    # Sheet 4: Sale Types & Bill Sundries
    ws_types = wb.create_sheet(title="Sale Types & Sundries")
    ws_types.append(["Sale Types Available", "", "Bill Sundries Available"])
    _apply_header_style(ws_types, ["Sale Types Available", "", "Bill Sundries Available"], bg_color="558B2F")
    sale_types = list(SaleType.objects.all().order_by("name"))
    sundries = list(BillSundry.objects.all().order_by("name"))
    max_len = max(len(sale_types), len(sundries), 1)
    for i in range(max_len):
        st_name = sale_types[i].name if i < len(sale_types) else ""
        bs_name = sundries[i].name if i < len(sundries) else ""
        ws_types.append([st_name, "", bs_name])
    _auto_adjust_columns(ws_types)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def import_sales_from_excel(file_obj, default_sale_type_id=None, update_existing=False):
    """
    Parse an Excel file and import Sale Vouchers with items and bill sundries.
    Validates that Account, Item, and BillSundry exist in the database.
    """
    check_openpyxl()
    from .models import Account, Item, Unit, Sale, SaleItem, SaleBillSundry, SaleType, BillSundry

    result = {
        "success": False,
        "total_rows": 0,
        "vouchers_created": 0,
        "vouchers_updated": 0,
        "vouchers_skipped": 0,
        "items_count": 0,
        "errors": [],
    }

    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
        ws = wb.active
    except Exception as e:
        result["errors"].append(f"Could not open Excel file: {str(e)}")
        return result

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        result["errors"].append("The Excel file is empty.")
        return result

    header_row = rows[0]
    header_map = {}
    for idx, cell in enumerate(header_row):
        norm = _normalize_header(cell)
        if norm:
            header_map[norm] = idx

    def get_val(row, *aliases):
        for alias in aliases:
            norm = _normalize_header(alias)
            if norm in header_map:
                col_idx = header_map[norm]
                if col_idx < len(row):
                    return row[col_idx]
        return None

    # Cache masters for fast lookup
    account_cache = {a.account_name.lower(): a for a in Account.objects.all()}
    item_cache = {i.item_name.lower(): i for i in Item.objects.select_related("main_unit").all()}
    unit_cache = {u.name.lower(): u for u in Unit.objects.all()}
    sale_type_cache = {st.name.lower(): st for st in SaleType.objects.all()}
    sundry_cache = {bs.name.lower(): bs for bs in BillSundry.objects.all()}

    default_sale_type = None
    if default_sale_type_id:
        default_sale_type = SaleType.objects.filter(id=default_sale_type_id).first()
    if not default_sale_type:
        default_sale_type = sale_type_cache.get("local sale") or SaleType.objects.first()

    grouped_invoices = {}
    row_errors = []

    # Carry-forward state: users often fill Invoice No / Date / Party only on
    # the first item row of an invoice (Busy / Tally export style).
    _last_inv_no = ""
    _last_raw_date = None
    _last_party_str = ""
    _last_sale_type_str = ""

    for row_idx, row in enumerate(rows[1:], start=2):
        if not any(row):
            continue

        result["total_rows"] += 1

        inv_no = _clean_str(get_val(row, "Invoice No *", "Invoice No", "Invoice", "inv_no", "invoice_no"))
        # Carry forward from the previous row if blank
        if not inv_no:
            inv_no = _last_inv_no
        if not inv_no:
            row_errors.append(f"Row {row_idx}: 'Invoice No' is required.")
            continue
        _last_inv_no = inv_no

        raw_date = get_val(row, "Date *", "Date", "date")
        if raw_date is None or _clean_str(raw_date) == "":
            raw_date = _last_raw_date
        else:
            _last_raw_date = raw_date
        date_obj = _parse_date(raw_date)

        party_str = _clean_str(get_val(row, "Party (Customer) *", "Party", "Customer", "Account", "account", "party"))
        if not party_str:
            party_str = _last_party_str
        else:
            _last_party_str = party_str

        sale_type_str = _clean_str(get_val(row, "Sale Type", "sale_type", "type"))
        if not sale_type_str:
            sale_type_str = _last_sale_type_str
        else:
            _last_sale_type_str = sale_type_str

        item_str = _clean_str(get_val(row, "Item Name *", "Item Name", "Item", "item_name", "item"))
        unit_str = _clean_str(get_val(row, "Unit", "unit"))
        qty_val = _parse_decimal(get_val(row, "Quantity *", "Quantity", "Qty", "quantity"), Decimal("0"))
        rate_val = _parse_decimal(get_val(row, "Rate", "rate", "Price"), None)
        discount_val = _parse_decimal(get_val(row, "Discount", "disc", "discount"), Decimal("0"))
        tax_val = _parse_decimal(get_val(row, "Tax Rate %", "Tax Rate", "Tax", "tax"), None)
        narration = _clean_str(get_val(row, "Narration", "narration", "Remarks"))

        # Validations for Item
        if not item_str:
            row_errors.append(f"Row {row_idx} (Inv {inv_no}): 'Item Name' is required.")
            continue

        item_obj = item_cache.get(item_str.lower())
        if not item_obj:
            row_errors.append(
                f"Row {row_idx} (Inv {inv_no}): Item '{item_str}' does not exist in database. "
                "Please create or import it in Items master first."
            )
            continue

        if qty_val <= 0:
            row_errors.append(f"Row {row_idx} (Inv {inv_no}): Quantity must be greater than 0.")
            continue

        # Rate defaults to item sale price if not given
        if rate_val is None:
            rate_val = item_obj.sale_price

        # Tax defaults to item tax if not given
        if tax_val is None:
            tax_val = item_obj.tax

        # Unit
        unit_obj = None
        if unit_str:
            unit_obj = unit_cache.get(unit_str.lower())
        if not unit_obj:
            unit_obj = item_obj.main_unit

        # Group under invoice number
        if inv_no not in grouped_invoices:
            # Party validation for invoice
            if not party_str:
                row_errors.append(f"Row {row_idx} (Inv {inv_no}): 'Party (Customer)' is required for the invoice.")
                continue

            party_obj = account_cache.get(party_str.lower())
            if not party_obj:
                row_errors.append(
                    f"Row {row_idx} (Inv {inv_no}): Account '{party_str}' does not exist in database. "
                    "Please create or import it in Accounts master first."
                )
                continue

            if not date_obj:
                date_obj = datetime.date.today()

            st_obj = sale_type_cache.get(sale_type_str.lower()) if sale_type_str else default_sale_type
            if not st_obj:
                st_obj = default_sale_type

            grouped_invoices[inv_no] = {
                "date": date_obj,
                "invoice_no": inv_no,
                "account": party_obj,
                "sale_type": st_obj,
                "narration": narration,
                "items": [],
                "sundries": [],
            }
        else:
            if narration and not grouped_invoices[inv_no]["narration"]:
                grouped_invoices[inv_no]["narration"] = narration

        grouped_invoices[inv_no]["items"].append({
            "item": item_obj,
            "unit": unit_obj,
            "quantity": qty_val,
            "rate": rate_val,
            "discount": discount_val,
            "tax": tax_val,
        })

        # Process multiple overall bill sundries (Bill Sundry 1..3, or generic Bill Sundry)
        sundry_col_pairs = [
            ("Bill Sundry 1", "Sundry Amount 1"),
            ("Bill Sundry 2", "Sundry Amount 2"),
            ("Bill Sundry 3", "Sundry Amount 3"),
            ("Bill Sundry", "Sundry Amount"),
        ]
        for s_col, a_col in sundry_col_pairs:
            s_name = _clean_str(get_val(row, s_col))
            if s_name:
                s_obj = sundry_cache.get(s_name.lower())
                if not s_obj:
                    row_errors.append(
                        f"Row {row_idx} (Inv {inv_no}): Bill Sundry '{s_name}' does not exist in database. "
                        "Please create it in Bill Sundry master first."
                    )
                    continue
                s_amt = _parse_decimal(get_val(row, a_col), Decimal("0"))
                # Avoid duplicate sundry for the same invoice
                existing_sundry_ids = {s["bill_sundry"].id for s in grouped_invoices[inv_no]["sundries"]}
                if s_obj.id not in existing_sundry_ids:
                    grouped_invoices[inv_no]["sundries"].append({
                        "bill_sundry": s_obj,
                        "amount": s_amt,
                    })

    if row_errors:
        result["errors"].extend(row_errors)
        return result

    # Save to database inside atomic transaction
    with transaction.atomic():
        for inv_no, inv_data in grouped_invoices.items():
            existing = Sale.objects.filter(invoice_no=inv_no).first()
            if existing:
                if update_existing:
                    existing.date = inv_data["date"]
                    existing.account = inv_data["account"]
                    existing.sale_type = inv_data["sale_type"]
                    existing.narration = inv_data["narration"]
                    existing.save()
                    existing.items.all().delete()
                    existing.bill_sundries.all().delete()
                    sale_obj = existing
                    result["vouchers_updated"] += 1
                else:
                    result["vouchers_skipped"] += 1
                    continue
            else:
                sale_obj = Sale.objects.create(
                    date=inv_data["date"],
                    invoice_no=inv_no,
                    account=inv_data["account"],
                    sale_type=inv_data["sale_type"],
                    narration=inv_data["narration"],
                )
                result["vouchers_created"] += 1

            # bulk_create deliberately bypasses SaleItem.save(), whose
            # convenience default replaces an explicit tax value of 0 with the
            # item's master tax. The importer has already applied the master
            # tax only when the Excel cell was blank, so an entered 0 is kept.
            SaleItem.objects.bulk_create([
                SaleItem(
                    sale=sale_obj,
                    item=itm["item"],
                    unit=itm["unit"],
                    quantity=itm["quantity"],
                    rate=itm["rate"],
                    discount=itm["discount"],
                    tax=itm["tax"],
                )
                for itm in inv_data["items"]
            ])
            result["items_count"] += len(inv_data["items"])

            for snd in inv_data["sundries"]:
                SaleBillSundry.objects.create(
                    sale=sale_obj,
                    bill_sundry=snd["bill_sundry"],
                    amount=snd["amount"],
                )

    result["success"] = (result["vouchers_created"] > 0 or result["vouchers_updated"] > 0 or (result["vouchers_skipped"] > 0 and not result["errors"]))
    return result


# ==============================================================================
# PURCHASE VOUCHER TEMPLATE & IMPORT
# ==============================================================================

PURCHASE_VOUCHER_HEADERS = [
    "Date *",
    "Invoice No *",
    "Party (Supplier) *",
    "Purchase Type",
    "Item Name *",
    "Unit",
    "Quantity *",
    "Rate",
    "Discount",
    "Tax Rate %",
    "Bill Sundry 1",
    "Sundry Amount 1",
    "Bill Sundry 2",
    "Sundry Amount 2",
    "Bill Sundry 3",
    "Sundry Amount 3",
    "Narration",
]

PURCHASE_SAMPLE_ROWS = [
    [
        "2026-09-01",
        "PUR-501",
        "National Steel Corporation",
        "Local Purchase",
        "Laptop Dell Inspiron 15",
        "PCS",
        5,
        48000.00,
        0.00,
        18,
        "Freight & Forwarding Charges",
        800.00,
        "Rounded Off",
        0.00,
        "",
        0.00,
        "Purchased from primary supplier",
    ],
    [
        "2026-09-01",
        "PUR-501",
        "National Steel Corporation",
        "Local Purchase",
        "Cotton T-Shirt Blue M",
        "PCS",
        20,
        320.00,
        0.00,
        5,
        "",
        0.00,
        "",
        0.00,
        "",
        0.00,
        "",
    ],
    [
        "2026-09-02",
        "PUR-502",
        "National Steel Corporation",
        "Local Purchase",
        "Basmati Rice Royal 25kg",
        "BAG",
        25,
        1950.00,
        500.00,
        0,
        "Rounded Off",
        0.00,
        "",
        0.00,
        "",
        0.00,
        "Stock delivered to godown",
    ],
]


def generate_purchase_template():
    """Generate and return an in-memory .xlsx template for Purchase voucher import."""
    check_openpyxl()
    from .models import Account, Item, PurchaseType, BillSundry

    wb = openpyxl.Workbook()

    # Sheet 1: Purchase Invoices Template
    ws = wb.active
    ws.title = "Purchase Invoices"
    _apply_header_style(ws, PURCHASE_VOUCHER_HEADERS, bg_color="2C5E3B")
    for r in PURCHASE_SAMPLE_ROWS:
        ws.append(r)
    _auto_adjust_columns(ws)

    # Sheet 2: Existing Suppliers & Accounts Reference
    ws_acc = wb.create_sheet(title="Existing Suppliers & Accounts")
    ws_acc.append(["Account Name", "Group", "State", "GSTIN"])
    _apply_header_style(ws_acc, ["Account Name", "Group", "State", "GSTIN"], bg_color="388E3C")
    for acc in Account.objects.select_related("account_group").order_by("account_name")[:200]:
        ws_acc.append([acc.account_name, acc.account_group.name if acc.account_group else "", acc.state, acc.gst])
    _auto_adjust_columns(ws_acc)

    # Sheet 3: Existing Items Reference
    ws_items = wb.create_sheet(title="Existing Items")
    ws_items.append(["Item Name", "Main Unit", "Purchase Price", "Tax Rate %"])
    _apply_header_style(ws_items, ["Item Name", "Main Unit", "Purchase Price", "Tax Rate %"], bg_color="558B2F")
    for itm in Item.objects.select_related("main_unit").order_by("item_name")[:200]:
        ws_items.append([itm.item_name, itm.main_unit.name if itm.main_unit else "", float(itm.purchase_price), float(itm.tax)])
    _auto_adjust_columns(ws_items)

    # Sheet 4: Purchase Types & Bill Sundries
    ws_types = wb.create_sheet(title="Purchase Types & Sundries")
    ws_types.append(["Purchase Types Available", "", "Bill Sundries Available"])
    _apply_header_style(ws_types, ["Purchase Types Available", "", "Bill Sundries Available"], bg_color="689F38")
    purchase_types = list(PurchaseType.objects.all().order_by("name"))
    sundries = list(BillSundry.objects.all().order_by("name"))
    max_len = max(len(purchase_types), len(sundries), 1)
    for i in range(max_len):
        pt_name = purchase_types[i].name if i < len(purchase_types) else ""
        bs_name = sundries[i].name if i < len(sundries) else ""
        ws_types.append([pt_name, "", bs_name])
    _auto_adjust_columns(ws_types)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def import_purchases_from_excel(file_obj, default_purchase_type_id=None, update_existing=False):
    """
    Parse an Excel file and import Purchase Vouchers with items and bill sundries.
    Validates that Account, Item, and BillSundry exist in the database.
    """
    check_openpyxl()
    from .models import Account, Item, Unit, Purchase, PurchaseItem, PurchaseBillSundry, PurchaseType, BillSundry

    result = {
        "success": False,
        "total_rows": 0,
        "vouchers_created": 0,
        "vouchers_updated": 0,
        "vouchers_skipped": 0,
        "items_count": 0,
        "errors": [],
    }

    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
        ws = wb.active
    except Exception as e:
        result["errors"].append(f"Could not open Excel file: {str(e)}")
        return result

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        result["errors"].append("The Excel file is empty.")
        return result

    header_row = rows[0]
    header_map = {}
    for idx, cell in enumerate(header_row):
        norm = _normalize_header(cell)
        if norm:
            header_map[norm] = idx

    def get_val(row, *aliases):
        for alias in aliases:
            norm = _normalize_header(alias)
            if norm in header_map:
                col_idx = header_map[norm]
                if col_idx < len(row):
                    return row[col_idx]
        return None

    account_cache = {a.account_name.lower(): a for a in Account.objects.all()}
    item_cache = {i.item_name.lower(): i for i in Item.objects.select_related("main_unit").all()}
    unit_cache = {u.name.lower(): u for u in Unit.objects.all()}
    purchase_type_cache = {pt.name.lower(): pt for pt in PurchaseType.objects.all()}
    sundry_cache = {bs.name.lower(): bs for bs in BillSundry.objects.all()}

    default_purchase_type = None
    if default_purchase_type_id:
        default_purchase_type = PurchaseType.objects.filter(id=default_purchase_type_id).first()
    if not default_purchase_type:
        default_purchase_type = purchase_type_cache.get("local purchase") or PurchaseType.objects.first()

    grouped_invoices = {}
    row_errors = []

    # Carry-forward state: users often fill Invoice No / Date / Party only on
    # the first item row of an invoice (Busy / Tally export style).
    _last_inv_no = ""
    _last_raw_date = None
    _last_party_str = ""
    _last_purchase_type_str = ""

    for row_idx, row in enumerate(rows[1:], start=2):
        if not any(row):
            continue

        result["total_rows"] += 1

        inv_no = _clean_str(get_val(row, "Invoice No *", "Invoice No", "Bill No", "Invoice", "inv_no", "invoice_no"))
        # Carry forward from the previous row if blank
        if not inv_no:
            inv_no = _last_inv_no
        if not inv_no:
            row_errors.append(f"Row {row_idx}: 'Invoice No' is required.")
            continue
        _last_inv_no = inv_no

        raw_date = get_val(row, "Date *", "Date", "date")
        if raw_date is None or _clean_str(raw_date) == "":
            raw_date = _last_raw_date
        else:
            _last_raw_date = raw_date
        date_obj = _parse_date(raw_date)

        party_str = _clean_str(get_val(row, "Party (Supplier) *", "Party", "Supplier", "Account", "account", "party"))
        if not party_str:
            party_str = _last_party_str
        else:
            _last_party_str = party_str

        purchase_type_str = _clean_str(get_val(row, "Purchase Type", "purchase_type", "type"))
        if not purchase_type_str:
            purchase_type_str = _last_purchase_type_str
        else:
            _last_purchase_type_str = purchase_type_str

        item_str = _clean_str(get_val(row, "Item Name *", "Item Name", "Item", "item_name", "item"))
        unit_str = _clean_str(get_val(row, "Unit", "unit"))
        qty_val = _parse_decimal(get_val(row, "Quantity *", "Quantity", "Qty", "quantity"), Decimal("0"))
        rate_val = _parse_decimal(get_val(row, "Rate", "rate", "Price"), None)
        discount_val = _parse_decimal(get_val(row, "Discount", "disc", "discount"), Decimal("0"))
        tax_val = _parse_decimal(get_val(row, "Tax Rate %", "Tax Rate", "Tax", "tax"), None)
        narration = _clean_str(get_val(row, "Narration", "narration", "Remarks"))

        if not item_str:
            row_errors.append(f"Row {row_idx} (Inv {inv_no}): 'Item Name' is required.")
            continue

        item_obj = item_cache.get(item_str.lower())
        if not item_obj:
            row_errors.append(
                f"Row {row_idx} (Inv {inv_no}): Item '{item_str}' does not exist in database. "
                "Please create or import it in Items master first."
            )
            continue

        if qty_val <= 0:
            row_errors.append(f"Row {row_idx} (Inv {inv_no}): Quantity must be greater than 0.")
            continue

        if rate_val is None:
            rate_val = item_obj.purchase_price

        if tax_val is None:
            tax_val = item_obj.tax

        unit_obj = None
        if unit_str:
            unit_obj = unit_cache.get(unit_str.lower())
        if not unit_obj:
            unit_obj = item_obj.main_unit

        if inv_no not in grouped_invoices:
            if not party_str:
                row_errors.append(f"Row {row_idx} (Inv {inv_no}): 'Party (Supplier)' is required for the invoice.")
                continue

            party_obj = account_cache.get(party_str.lower())
            if not party_obj:
                row_errors.append(
                    f"Row {row_idx} (Inv {inv_no}): Account '{party_str}' does not exist in database. "
                    "Please create or import it in Accounts master first."
                )
                continue

            if not date_obj:
                date_obj = datetime.date.today()

            pt_obj = purchase_type_cache.get(purchase_type_str.lower()) if purchase_type_str else default_purchase_type
            if not pt_obj:
                pt_obj = default_purchase_type

            grouped_invoices[inv_no] = {
                "date": date_obj,
                "invoice_no": inv_no,
                "account": party_obj,
                "purchase_type": pt_obj,
                "narration": narration,
                "items": [],
                "sundries": [],
            }
        else:
            if narration and not grouped_invoices[inv_no]["narration"]:
                grouped_invoices[inv_no]["narration"] = narration

        grouped_invoices[inv_no]["items"].append({
            "item": item_obj,
            "unit": unit_obj,
            "quantity": qty_val,
            "rate": rate_val,
            "discount": discount_val,
            "tax": tax_val,
        })

        # Process multiple overall bill sundries (Bill Sundry 1..3, or generic Bill Sundry)
        sundry_col_pairs = [
            ("Bill Sundry 1", "Sundry Amount 1"),
            ("Bill Sundry 2", "Sundry Amount 2"),
            ("Bill Sundry 3", "Sundry Amount 3"),
            ("Bill Sundry", "Sundry Amount"),
        ]
        for s_col, a_col in sundry_col_pairs:
            s_name = _clean_str(get_val(row, s_col))
            if s_name:
                s_obj = sundry_cache.get(s_name.lower())
                if not s_obj:
                    row_errors.append(
                        f"Row {row_idx} (Inv {inv_no}): Bill Sundry '{s_name}' does not exist in database. "
                        "Please create it in Bill Sundry master first."
                    )
                    continue
                s_amt = _parse_decimal(get_val(row, a_col), Decimal("0"))
                existing_sundry_ids = {s["bill_sundry"].id for s in grouped_invoices[inv_no]["sundries"]}
                if s_obj.id not in existing_sundry_ids:
                    grouped_invoices[inv_no]["sundries"].append({
                        "bill_sundry": s_obj,
                        "amount": s_amt,
                    })

    if row_errors:
        result["errors"].extend(row_errors)
        return result

    with transaction.atomic():
        for inv_no, inv_data in grouped_invoices.items():
            existing = Purchase.objects.filter(invoice_no=inv_no).first()
            if existing:
                if update_existing:
                    existing.date = inv_data["date"]
                    existing.account = inv_data["account"]
                    existing.purchase_type = inv_data["purchase_type"]
                    existing.narration = inv_data["narration"]
                    existing.save()
                    existing.items.all().delete()
                    existing.bill_sundries.all().delete()
                    purchase_obj = existing
                    result["vouchers_updated"] += 1
                else:
                    result["vouchers_skipped"] += 1
                    continue
            else:
                purchase_obj = Purchase.objects.create(
                    date=inv_data["date"],
                    invoice_no=inv_no,
                    account=inv_data["account"],
                    purchase_type=inv_data["purchase_type"],
                    narration=inv_data["narration"],
                )
                result["vouchers_created"] += 1

            # See the matching sale import: an explicit Excel tax of 0 must
            # not be replaced by the item's master tax.
            PurchaseItem.objects.bulk_create([
                PurchaseItem(
                    purchase=purchase_obj,
                    item=itm["item"],
                    unit=itm["unit"],
                    quantity=itm["quantity"],
                    rate=itm["rate"],
                    discount=itm["discount"],
                    tax=itm["tax"],
                )
                for itm in inv_data["items"]
            ])
            result["items_count"] += len(inv_data["items"])

            for snd in inv_data["sundries"]:
                PurchaseBillSundry.objects.create(
                    purchase=purchase_obj,
                    bill_sundry=snd["bill_sundry"],
                    amount=snd["amount"],
                )

    result["success"] = (result["vouchers_created"] > 0 or result["vouchers_updated"] > 0 or (result["vouchers_skipped"] > 0 and not result["errors"]))
    return result


# ==============================================================================
# PAYMENT, RECEIPT & JOURNAL VOUCHER TEMPLATE / IMPORT
# ==============================================================================

PAYMENT_VOUCHER_HEADERS = ["Date *", "Voucher No *", "Through (Cash/Bank) *", "Party / Expense *", "Amount *", "Narration"]
RECEIPT_VOUCHER_HEADERS = ["Date *", "Voucher No *", "Through (Cash/Bank) *", "Party / Income *", "Amount *", "Narration"]
JOURNAL_VOUCHER_HEADERS = ["Date *", "Voucher No *", "Account *", "Debit", "Credit", "Remarks", "Narration"]


def _voucher_template(title, headers, rows, account_headers):
    check_openpyxl()
    from .models import Account

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    _apply_header_style(ws, headers, bg_color="1F497D")
    for row in rows:
        ws.append(row)
    _auto_adjust_columns(ws)

    ws_accounts = wb.create_sheet(title="Existing Accounts")
    _apply_header_style(ws_accounts, account_headers, bg_color="366092")
    for account in Account.objects.select_related("account_group").order_by("account_name")[:500]:
        ws_accounts.append([account.account_name, account.account_group.name])
    _auto_adjust_columns(ws_accounts)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def generate_payment_template():
    return _voucher_template(
        "Payment Vouchers",
        PAYMENT_VOUCHER_HEADERS,
        [
            ["2026-09-06", "PMT-0001", "Cash", "National Steel Corporation", 15000, "Supplier payments"],
            ["", "PMT-0001", "", "Freight & Forwarding Charges", 2500, ""],
        ],
        ["Account Name", "Group"],
    )


def generate_receipt_template():
    return _voucher_template(
        "Receipt Vouchers",
        RECEIPT_VOUCHER_HEADERS,
        [
            ["2026-09-06", "RCT-0001", "HDFC Bank", "Apex Infotech Pvt Ltd", 20000, "Customer receipts"],
            ["", "RCT-0001", "", "Walk-in Customer", 5000, ""],
        ],
        ["Account Name", "Group"],
    )


def generate_journal_template():
    return _voucher_template(
        "Journal Vouchers",
        JOURNAL_VOUCHER_HEADERS,
        [
            ["2026-09-06", "JRN-0001", "Office Rent", 12000, "", "September rent", "Monthly adjustment"],
            ["", "JRN-0001", "Rent Payable", "", 12000, "", ""],
        ],
        ["Account Name", "Group"],
    )


def _load_import_rows(file_obj):
    try:
        workbook = openpyxl.load_workbook(file_obj, data_only=True)
        rows = list(workbook.active.iter_rows(values_only=True))
    except Exception as exc:
        return None, [f"Could not open Excel file: {str(exc)}"]
    if not rows:
        return None, ["The Excel file is empty."]
    header_map = {}
    for index, cell in enumerate(rows[0]):
        normalized = _normalize_header(cell)
        if normalized:
            header_map[normalized] = index
    return (rows[1:], header_map), []


def _row_value(row, header_map, *aliases):
    for alias in aliases:
        index = header_map.get(_normalize_header(alias))
        if index is not None and index < len(row):
            return row[index]
    return None


def _cash_voucher_result():
    return {"success": False, "total_rows": 0, "vouchers_created": 0, "vouchers_updated": 0, "vouchers_skipped": 0, "items_count": 0, "errors": []}


def _import_cash_vouchers(file_obj, voucher_model, line_model, party_header, update_existing=False):
    """Import a Payment or Receipt header with one or more account lines."""
    check_openpyxl()
    from .models import Account

    result = _cash_voucher_result()
    loaded, errors = _load_import_rows(file_obj)
    if errors:
        result["errors"] = errors
        return result
    rows, header_map = loaded
    accounts = {account.account_name.lower(): account for account in Account.objects.select_related("account_group")}
    grouped, row_errors = {}, []

    # Carry-forward state for multi-line vouchers (Busy / Tally export style).
    _last_voucher_no = ""
    _last_raw_date = None
    _last_through_name = ""
    _last_narration = ""

    for row_number, row in enumerate(rows, start=2):
        if not any(row):
            continue
        result["total_rows"] += 1

        voucher_no = _clean_str(_row_value(row, header_map, "Voucher No *", "Voucher No", "voucher_no"))
        if not voucher_no:
            voucher_no = _last_voucher_no
        if not voucher_no:
            row_errors.append(f"Row {row_number}: 'Voucher No' is required.")
            continue
        _last_voucher_no = voucher_no

        party_name = _clean_str(_row_value(row, header_map, party_header, "Party", "Account"))
        amount = _parse_decimal(_row_value(row, header_map, "Amount *", "Amount", "amount"), Decimal("0"))
        if not party_name or amount <= 0:
            row_errors.append(f"Row {row_number} ({voucher_no}): party/account and an amount greater than 0 are required.")
            continue
        party = accounts.get(party_name.lower())
        if not party:
            row_errors.append(f"Row {row_number} ({voucher_no}): Account '{party_name}' does not exist.")
            continue

        if voucher_no not in grouped:
            through_name = _clean_str(_row_value(row, header_map, "Through (Cash/Bank) *", "Through", "Cash Bank"))
            if not through_name:
                through_name = _last_through_name
            else:
                _last_through_name = through_name
            through = accounts.get(through_name.lower())
            if not through_name or not through:
                row_errors.append(f"Row {row_number} ({voucher_no}): a valid cash/bank Through account is required on the first row.")
                continue
            if through.account_group.name not in ("Cash-in-hand", "Bank Accounts"):
                row_errors.append(f"Row {row_number} ({voucher_no}): Through account '{through_name}' must be in Cash-in-hand or Bank Accounts.")
                continue

            raw_date = _row_value(row, header_map, "Date *", "Date")
            if raw_date is None or _clean_str(raw_date) == "":
                raw_date = _last_raw_date
            else:
                _last_raw_date = raw_date
            voucher_date = _parse_date(raw_date)
            if not voucher_date:
                row_errors.append(f"Row {row_number} ({voucher_no}): a valid Date is required on the first row.")
                continue

            narration = _clean_str(_row_value(row, header_map, "Narration", "Remarks"))
            if not narration:
                narration = _last_narration
            else:
                _last_narration = narration

            grouped[voucher_no] = {"date": voucher_date, "through": through, "narration": narration, "lines": []}
        grouped[voucher_no]["lines"].append({"account": party, "amount": amount})

    if row_errors:
        result["errors"] = row_errors
        return result
    with transaction.atomic():
        for voucher_no, data in grouped.items():
            voucher = voucher_model.objects.filter(voucher_no=voucher_no).first()
            if voucher and not update_existing:
                result["vouchers_skipped"] += 1
                continue
            if voucher:
                voucher.date, voucher.through, voucher.narration = data["date"], data["through"], data["narration"]
                voucher.save()
                voucher.lines.all().delete()
                result["vouchers_updated"] += 1
            else:
                voucher = voucher_model.objects.create(voucher_no=voucher_no, date=data["date"], through=data["through"], narration=data["narration"])
                result["vouchers_created"] += 1
            line_model.objects.bulk_create([line_model(**{voucher_model.__name__.lower(): voucher, **line}) for line in data["lines"]])
            result["items_count"] += len(data["lines"])
    result["success"] = bool(result["vouchers_created"] or result["vouchers_updated"] or result["vouchers_skipped"])
    return result


def import_payments_from_excel(file_obj, update_existing=False):
    from .models import Payment, PaymentLine
    return _import_cash_vouchers(file_obj, Payment, PaymentLine, "Party / Expense *", update_existing)


def import_receipts_from_excel(file_obj, update_existing=False):
    from .models import Receipt, ReceiptLine
    return _import_cash_vouchers(file_obj, Receipt, ReceiptLine, "Party / Income *", update_existing)


# ==============================================================================
# SALE RETURN VOUCHER TEMPLATE & IMPORT
# ==============================================================================

SALE_RETURN_VOUCHER_HEADERS = [
    "Date *",
    "Voucher No",
    "Party (Customer) *",
    "Sale Type",
    "Against Sale Invoice",
    "Item Name *",
    "Unit",
    "Quantity *",
    "Rate",
    "Discount",
    "Tax Rate %",
    "Bill Sundry 1",
    "Sundry Amount 1",
    "Bill Sundry 2",
    "Sundry Amount 2",
    "Bill Sundry 3",
    "Sundry Amount 3",
    "Narration",
]

SALE_RETURN_SAMPLE_ROWS = [
    [
        "2026-09-05",
        "SR-001",
        "Apex Infotech Pvt Ltd",
        "Local Sale",
        "INV-001",
        "Laptop Dell Inspiron 15",
        "PCS",
        1,
        55000.00,
        0.00,
        18,
        "",
        0.00,
        "",
        0.00,
        "",
        0.00,
        "Customer returned damaged unit",
    ],
    [
        "2026-09-06",
        "SR-002",
        "Apex Infotech Pvt Ltd",
        "Local Sale",
        "",
        "Cotton T-Shirt Blue M",
        "PCS",
        2,
        499.00,
        0.00,
        5,
        "Rounded Off",
        0.00,
        "",
        0.00,
        "",
        0.00,
        "Wrong colour returned",
    ],
]


def generate_sale_return_template():
    """Generate and return an in-memory .xlsx template for Sale Return voucher import."""
    check_openpyxl()
    from .models import Account, Item, SaleType, BillSundry, Sale

    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "Sale Returns"
    _apply_header_style(ws, SALE_RETURN_VOUCHER_HEADERS, bg_color="7B3F00")
    for r in SALE_RETURN_SAMPLE_ROWS:
        ws.append(r)
    _auto_adjust_columns(ws)

    ws_acc = wb.create_sheet(title="Existing Customers & Accounts")
    _apply_header_style(ws_acc, ["Account Name", "Group", "State", "GSTIN"], bg_color="366092")
    for acc in Account.objects.select_related("account_group").order_by("account_name")[:200]:
        ws_acc.append([acc.account_name, acc.account_group.name if acc.account_group else "", acc.state, acc.gst])
    _auto_adjust_columns(ws_acc)

    ws_items = wb.create_sheet(title="Existing Items")
    _apply_header_style(ws_items, ["Item Name", "Main Unit", "Sale Price", "Tax Rate %"], bg_color="4F81BD")
    for itm in Item.objects.select_related("main_unit").order_by("item_name")[:200]:
        ws_items.append([itm.item_name, itm.main_unit.name if itm.main_unit else "", float(itm.sale_price), float(itm.tax)])
    _auto_adjust_columns(ws_items)

    ws_types = wb.create_sheet(title="Sale Types & Sundries")
    _apply_header_style(ws_types, ["Sale Types Available", "", "Bill Sundries Available"], bg_color="558B2F")
    sale_types = list(SaleType.objects.all().order_by("name"))
    sundries = list(BillSundry.objects.all().order_by("name"))
    max_len = max(len(sale_types), len(sundries), 1)
    for i in range(max_len):
        st_name = sale_types[i].name if i < len(sale_types) else ""
        bs_name = sundries[i].name if i < len(sundries) else ""
        ws_types.append([st_name, "", bs_name])
    _auto_adjust_columns(ws_types)

    ws_sales = wb.create_sheet(title="Existing Sales (for Against)")
    _apply_header_style(ws_sales, ["Invoice No", "Date", "Party"], bg_color="8E44AD")
    for s in Sale.objects.select_related("account").order_by("-date")[:200]:
        ws_sales.append([s.invoice_no, str(s.date), s.account.account_name])
    _auto_adjust_columns(ws_sales)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def import_sale_returns_from_excel(file_obj, default_sale_type_id=None, update_existing=False):
    """
    Parse an Excel file and import Sale Return Vouchers with items and bill sundries.
    Mirrors import_sales_from_excel; key differences: model is SaleReturn, voucher
    identifier is voucher_no (auto-assigned if blank), and an optional
    'Against Sale Invoice' column links the return to the original Sale.
    """
    check_openpyxl()
    from .models import (
        Account, Item, Unit, Sale, SaleType, BillSundry,
        SaleReturn, SaleReturnItem, SaleReturnBillSundry,
    )

    result = {
        "success": False,
        "total_rows": 0,
        "vouchers_created": 0,
        "vouchers_updated": 0,
        "vouchers_skipped": 0,
        "items_count": 0,
        "errors": [],
    }

    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
        ws = wb.active
    except Exception as e:
        result["errors"].append(f"Could not open Excel file: {str(e)}")
        return result

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        result["errors"].append("The Excel file is empty.")
        return result

    header_row = rows[0]
    header_map = {}
    for idx, cell in enumerate(header_row):
        norm = _normalize_header(cell)
        if norm:
            header_map[norm] = idx

    def get_val(row, *aliases):
        for alias in aliases:
            norm = _normalize_header(alias)
            if norm in header_map:
                col_idx = header_map[norm]
                if col_idx < len(row):
                    return row[col_idx]
        return None

    account_cache = {a.account_name.lower(): a for a in Account.objects.all()}
    item_cache = {i.item_name.lower(): i for i in Item.objects.select_related("main_unit").all()}
    unit_cache = {u.name.lower(): u for u in Unit.objects.all()}
    sale_type_cache = {st.name.lower(): st for st in SaleType.objects.all()}
    sundry_cache = {bs.name.lower(): bs for bs in BillSundry.objects.all()}
    sale_cache = {s.invoice_no.lower(): s for s in Sale.objects.all()}

    default_sale_type = None
    if default_sale_type_id:
        default_sale_type = SaleType.objects.filter(id=default_sale_type_id).first()
    if not default_sale_type:
        default_sale_type = sale_type_cache.get("local sale") or SaleType.objects.first()

    grouped = {}
    row_errors = []

    _last_voucher_no = ""
    _last_raw_date = None
    _last_party_str = ""
    _last_sale_type_str = ""
    _last_against_str = ""

    for row_idx, row in enumerate(rows[1:], start=2):
        if not any(row):
            continue

        result["total_rows"] += 1

        voucher_no = _clean_str(get_val(row, "Voucher No", "voucher_no", "Voucher No *"))
        if not voucher_no:
            voucher_no = _last_voucher_no
        _last_voucher_no = voucher_no  # may be blank → auto-assigned later

        raw_date = get_val(row, "Date *", "Date", "date")
        if raw_date is None or _clean_str(raw_date) == "":
            raw_date = _last_raw_date
        else:
            _last_raw_date = raw_date
        date_obj = _parse_date(raw_date)

        party_str = _clean_str(get_val(row, "Party (Customer) *", "Party", "Customer", "Account"))
        if not party_str:
            party_str = _last_party_str
        else:
            _last_party_str = party_str

        sale_type_str = _clean_str(get_val(row, "Sale Type", "sale_type", "type"))
        if not sale_type_str:
            sale_type_str = _last_sale_type_str
        else:
            _last_sale_type_str = sale_type_str

        against_str = _clean_str(get_val(row, "Against Sale Invoice", "Against Sale", "Against Invoice", "against_sale"))
        if not against_str:
            against_str = _last_against_str
        else:
            _last_against_str = against_str

        item_str = _clean_str(get_val(row, "Item Name *", "Item Name", "Item", "item_name", "item"))
        unit_str = _clean_str(get_val(row, "Unit", "unit"))
        qty_val = _parse_decimal(get_val(row, "Quantity *", "Quantity", "Qty", "quantity"), Decimal("0"))
        rate_val = _parse_decimal(get_val(row, "Rate", "rate", "Price"), None)
        discount_val = _parse_decimal(get_val(row, "Discount", "disc", "discount"), Decimal("0"))
        tax_val = _parse_decimal(get_val(row, "Tax Rate %", "Tax Rate", "Tax", "tax"), None)
        narration = _clean_str(get_val(row, "Narration", "narration", "Remarks"))

        if not item_str:
            row_errors.append(f"Row {row_idx}: 'Item Name' is required.")
            continue

        item_obj = item_cache.get(item_str.lower())
        if not item_obj:
            row_errors.append(f"Row {row_idx}: Item '{item_str}' does not exist. Please create it in Items master first.")
            continue

        if qty_val <= 0:
            row_errors.append(f"Row {row_idx}: Quantity must be greater than 0.")
            continue

        if rate_val is None:
            rate_val = item_obj.sale_price
        if tax_val is None:
            tax_val = item_obj.tax

        unit_obj = unit_cache.get(unit_str.lower()) if unit_str else None
        if not unit_obj:
            unit_obj = item_obj.main_unit

        # Use voucher_no as grouping key; blank means it will be a new auto-numbered voucher.
        # We encode blank voucher_nos as a unique sentinel per date+party so that multiple
        # blank-voucher rows can still be grouped by the user's visible "block".
        group_key = voucher_no if voucher_no else f"__auto_{row_idx}__"

        if group_key not in grouped:
            if not party_str:
                row_errors.append(f"Row {row_idx}: 'Party (Customer)' is required.")
                continue

            party_obj = account_cache.get(party_str.lower())
            if not party_obj:
                row_errors.append(f"Row {row_idx}: Account '{party_str}' does not exist. Please create it in Accounts master first.")
                continue

            if not date_obj:
                date_obj = datetime.date.today()

            st_obj = sale_type_cache.get(sale_type_str.lower()) if sale_type_str else default_sale_type
            if not st_obj:
                st_obj = default_sale_type

            against_obj = sale_cache.get(against_str.lower()) if against_str else None

            grouped[group_key] = {
                "voucher_no": voucher_no,
                "date": date_obj,
                "account": party_obj,
                "sale_type": st_obj,
                "against_sale": against_obj,
                "narration": narration,
                "items": [],
                "sundries": [],
            }
        else:
            if narration and not grouped[group_key]["narration"]:
                grouped[group_key]["narration"] = narration

        grouped[group_key]["items"].append({
            "item": item_obj,
            "unit": unit_obj,
            "quantity": qty_val,
            "rate": rate_val,
            "discount": discount_val,
            "tax": tax_val,
        })

        sundry_col_pairs = [
            ("Bill Sundry 1", "Sundry Amount 1"),
            ("Bill Sundry 2", "Sundry Amount 2"),
            ("Bill Sundry 3", "Sundry Amount 3"),
            ("Bill Sundry", "Sundry Amount"),
        ]
        for s_col, a_col in sundry_col_pairs:
            s_name = _clean_str(get_val(row, s_col))
            if s_name:
                s_obj = sundry_cache.get(s_name.lower())
                if not s_obj:
                    row_errors.append(f"Row {row_idx}: Bill Sundry '{s_name}' does not exist. Please create it in Bill Sundry master first.")
                    continue
                s_amt = _parse_decimal(get_val(row, a_col), Decimal("0"))
                existing_ids = {s["bill_sundry"].id for s in grouped[group_key]["sundries"]}
                if s_obj.id not in existing_ids:
                    grouped[group_key]["sundries"].append({"bill_sundry": s_obj, "amount": s_amt})

    if row_errors:
        result["errors"].extend(row_errors)
        return result

    with transaction.atomic():
        for group_key, data in grouped.items():
            vno = data["voucher_no"]
            sr_obj = SaleReturn.objects.filter(voucher_no=vno).first() if vno else None
            if sr_obj:
                if update_existing:
                    sr_obj.date = data["date"]
                    sr_obj.account = data["account"]
                    sr_obj.sale_type = data["sale_type"]
                    sr_obj.against_sale = data["against_sale"]
                    sr_obj.narration = data["narration"]
                    sr_obj.save()
                    sr_obj.items.all().delete()
                    sr_obj.bill_sundries.all().delete()
                    result["vouchers_updated"] += 1
                else:
                    result["vouchers_skipped"] += 1
                    continue
            else:
                sr_obj = SaleReturn.objects.create(
                    voucher_no=vno or "",
                    date=data["date"],
                    account=data["account"],
                    sale_type=data["sale_type"],
                    against_sale=data["against_sale"],
                    narration=data["narration"],
                )
                result["vouchers_created"] += 1

            SaleReturnItem.objects.bulk_create([
                SaleReturnItem(
                    sale_return=sr_obj,
                    item=itm["item"],
                    unit=itm["unit"],
                    quantity=itm["quantity"],
                    rate=itm["rate"],
                    discount=itm["discount"],
                    tax=itm["tax"],
                )
                for itm in data["items"]
            ])
            result["items_count"] += len(data["items"])

            for snd in data["sundries"]:
                SaleReturnBillSundry.objects.create(
                    sale_return=sr_obj,
                    bill_sundry=snd["bill_sundry"],
                    amount=snd["amount"],
                )

    result["success"] = bool(result["vouchers_created"] or result["vouchers_updated"] or result["vouchers_skipped"])
    return result


# ==============================================================================
# PURCHASE RETURN VOUCHER TEMPLATE & IMPORT
# ==============================================================================

PURCHASE_RETURN_VOUCHER_HEADERS = [
    "Date *",
    "Voucher No",
    "Party (Supplier) *",
    "Purchase Type",
    "Against Purchase Invoice",
    "Item Name *",
    "Unit",
    "Quantity *",
    "Rate",
    "Discount",
    "Tax Rate %",
    "Bill Sundry 1",
    "Sundry Amount 1",
    "Bill Sundry 2",
    "Sundry Amount 2",
    "Bill Sundry 3",
    "Sundry Amount 3",
    "Narration",
]

PURCHASE_RETURN_SAMPLE_ROWS = [
    [
        "2026-09-05",
        "PR-001",
        "National Steel Corporation",
        "Local Purchase",
        "PUR-501",
        "Laptop Dell Inspiron 15",
        "PCS",
        2,
        48000.00,
        0.00,
        18,
        "",
        0.00,
        "",
        0.00,
        "",
        0.00,
        "Returned defective stock to supplier",
    ],
    [
        "2026-09-06",
        "PR-002",
        "National Steel Corporation",
        "Local Purchase",
        "",
        "Basmati Rice Royal 25kg",
        "BAG",
        5,
        1950.00,
        0.00,
        0,
        "Rounded Off",
        0.00,
        "",
        0.00,
        "",
        0.00,
        "Short supply – returned surplus",
    ],
]


def generate_purchase_return_template():
    """Generate and return an in-memory .xlsx template for Purchase Return voucher import."""
    check_openpyxl()
    from .models import Account, Item, PurchaseType, BillSundry, Purchase

    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "Purchase Returns"
    _apply_header_style(ws, PURCHASE_RETURN_VOUCHER_HEADERS, bg_color="4A235A")
    for r in PURCHASE_RETURN_SAMPLE_ROWS:
        ws.append(r)
    _auto_adjust_columns(ws)

    ws_acc = wb.create_sheet(title="Existing Suppliers & Accounts")
    _apply_header_style(ws_acc, ["Account Name", "Group", "State", "GSTIN"], bg_color="366092")
    for acc in Account.objects.select_related("account_group").order_by("account_name")[:200]:
        ws_acc.append([acc.account_name, acc.account_group.name if acc.account_group else "", acc.state, acc.gst])
    _auto_adjust_columns(ws_acc)

    ws_items = wb.create_sheet(title="Existing Items")
    _apply_header_style(ws_items, ["Item Name", "Main Unit", "Purchase Price", "Tax Rate %"], bg_color="4F81BD")
    for itm in Item.objects.select_related("main_unit").order_by("item_name")[:200]:
        ws_items.append([itm.item_name, itm.main_unit.name if itm.main_unit else "", float(itm.purchase_price), float(itm.tax)])
    _auto_adjust_columns(ws_items)

    ws_types = wb.create_sheet(title="Purchase Types & Sundries")
    _apply_header_style(ws_types, ["Purchase Types Available", "", "Bill Sundries Available"], bg_color="922B21")
    purchase_types = list(PurchaseType.objects.all().order_by("name"))
    sundries = list(BillSundry.objects.all().order_by("name"))
    max_len = max(len(purchase_types), len(sundries), 1)
    for i in range(max_len):
        pt_name = purchase_types[i].name if i < len(purchase_types) else ""
        bs_name = sundries[i].name if i < len(sundries) else ""
        ws_types.append([pt_name, "", bs_name])
    _auto_adjust_columns(ws_types)

    ws_pur = wb.create_sheet(title="Existing Purchases (for Against)")
    _apply_header_style(ws_pur, ["Invoice No", "Date", "Supplier"], bg_color="117A65")
    for p in Purchase.objects.select_related("account").order_by("-date")[:200]:
        ws_pur.append([p.invoice_no, str(p.date), p.account.account_name])
    _auto_adjust_columns(ws_pur)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def import_purchase_returns_from_excel(file_obj, default_purchase_type_id=None, update_existing=False):
    """
    Parse an Excel file and import Purchase Return Vouchers with items and bill sundries.
    Mirrors import_purchases_from_excel; key differences: model is PurchaseReturn and
    an optional 'Against Purchase Invoice' column links the return to the original Purchase.
    """
    check_openpyxl()
    from .models import (
        Account, Item, Unit, Purchase, PurchaseType, BillSundry,
        PurchaseReturn, PurchaseReturnItem, PurchaseReturnBillSundry,
    )

    result = {
        "success": False,
        "total_rows": 0,
        "vouchers_created": 0,
        "vouchers_updated": 0,
        "vouchers_skipped": 0,
        "items_count": 0,
        "errors": [],
    }

    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
        ws = wb.active
    except Exception as e:
        result["errors"].append(f"Could not open Excel file: {str(e)}")
        return result

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        result["errors"].append("The Excel file is empty.")
        return result

    header_row = rows[0]
    header_map = {}
    for idx, cell in enumerate(header_row):
        norm = _normalize_header(cell)
        if norm:
            header_map[norm] = idx

    def get_val(row, *aliases):
        for alias in aliases:
            norm = _normalize_header(alias)
            if norm in header_map:
                col_idx = header_map[norm]
                if col_idx < len(row):
                    return row[col_idx]
        return None

    account_cache = {a.account_name.lower(): a for a in Account.objects.all()}
    item_cache = {i.item_name.lower(): i for i in Item.objects.select_related("main_unit").all()}
    unit_cache = {u.name.lower(): u for u in Unit.objects.all()}
    purchase_type_cache = {pt.name.lower(): pt for pt in PurchaseType.objects.all()}
    sundry_cache = {bs.name.lower(): bs for bs in BillSundry.objects.all()}
    purchase_cache = {p.invoice_no.lower(): p for p in Purchase.objects.all()}

    default_purchase_type = None
    if default_purchase_type_id:
        default_purchase_type = PurchaseType.objects.filter(id=default_purchase_type_id).first()
    if not default_purchase_type:
        default_purchase_type = purchase_type_cache.get("local purchase") or PurchaseType.objects.first()

    grouped = {}
    row_errors = []

    _last_voucher_no = ""
    _last_raw_date = None
    _last_party_str = ""
    _last_purchase_type_str = ""
    _last_against_str = ""

    for row_idx, row in enumerate(rows[1:], start=2):
        if not any(row):
            continue

        result["total_rows"] += 1

        voucher_no = _clean_str(get_val(row, "Voucher No", "voucher_no", "Voucher No *"))
        if not voucher_no:
            voucher_no = _last_voucher_no
        _last_voucher_no = voucher_no

        raw_date = get_val(row, "Date *", "Date", "date")
        if raw_date is None or _clean_str(raw_date) == "":
            raw_date = _last_raw_date
        else:
            _last_raw_date = raw_date
        date_obj = _parse_date(raw_date)

        party_str = _clean_str(get_val(row, "Party (Supplier) *", "Party", "Supplier", "Account"))
        if not party_str:
            party_str = _last_party_str
        else:
            _last_party_str = party_str

        purchase_type_str = _clean_str(get_val(row, "Purchase Type", "purchase_type", "type"))
        if not purchase_type_str:
            purchase_type_str = _last_purchase_type_str
        else:
            _last_purchase_type_str = purchase_type_str

        against_str = _clean_str(get_val(row, "Against Purchase Invoice", "Against Purchase", "Against Invoice", "against_purchase"))
        if not against_str:
            against_str = _last_against_str
        else:
            _last_against_str = against_str

        item_str = _clean_str(get_val(row, "Item Name *", "Item Name", "Item", "item_name", "item"))
        unit_str = _clean_str(get_val(row, "Unit", "unit"))
        qty_val = _parse_decimal(get_val(row, "Quantity *", "Quantity", "Qty", "quantity"), Decimal("0"))
        rate_val = _parse_decimal(get_val(row, "Rate", "rate", "Price"), None)
        discount_val = _parse_decimal(get_val(row, "Discount", "disc", "discount"), Decimal("0"))
        tax_val = _parse_decimal(get_val(row, "Tax Rate %", "Tax Rate", "Tax", "tax"), None)
        narration = _clean_str(get_val(row, "Narration", "narration", "Remarks"))

        if not item_str:
            row_errors.append(f"Row {row_idx}: 'Item Name' is required.")
            continue

        item_obj = item_cache.get(item_str.lower())
        if not item_obj:
            row_errors.append(f"Row {row_idx}: Item '{item_str}' does not exist. Please create it in Items master first.")
            continue

        if qty_val <= 0:
            row_errors.append(f"Row {row_idx}: Quantity must be greater than 0.")
            continue

        if rate_val is None:
            rate_val = item_obj.purchase_price
        if tax_val is None:
            tax_val = item_obj.tax

        unit_obj = unit_cache.get(unit_str.lower()) if unit_str else None
        if not unit_obj:
            unit_obj = item_obj.main_unit

        group_key = voucher_no if voucher_no else f"__auto_{row_idx}__"

        if group_key not in grouped:
            if not party_str:
                row_errors.append(f"Row {row_idx}: 'Party (Supplier)' is required.")
                continue

            party_obj = account_cache.get(party_str.lower())
            if not party_obj:
                row_errors.append(f"Row {row_idx}: Account '{party_str}' does not exist. Please create it in Accounts master first.")
                continue

            if not date_obj:
                date_obj = datetime.date.today()

            pt_obj = purchase_type_cache.get(purchase_type_str.lower()) if purchase_type_str else default_purchase_type
            if not pt_obj:
                pt_obj = default_purchase_type

            against_obj = purchase_cache.get(against_str.lower()) if against_str else None

            grouped[group_key] = {
                "voucher_no": voucher_no,
                "date": date_obj,
                "account": party_obj,
                "purchase_type": pt_obj,
                "against_purchase": against_obj,
                "narration": narration,
                "items": [],
                "sundries": [],
            }
        else:
            if narration and not grouped[group_key]["narration"]:
                grouped[group_key]["narration"] = narration

        grouped[group_key]["items"].append({
            "item": item_obj,
            "unit": unit_obj,
            "quantity": qty_val,
            "rate": rate_val,
            "discount": discount_val,
            "tax": tax_val,
        })

        sundry_col_pairs = [
            ("Bill Sundry 1", "Sundry Amount 1"),
            ("Bill Sundry 2", "Sundry Amount 2"),
            ("Bill Sundry 3", "Sundry Amount 3"),
            ("Bill Sundry", "Sundry Amount"),
        ]
        for s_col, a_col in sundry_col_pairs:
            s_name = _clean_str(get_val(row, s_col))
            if s_name:
                s_obj = sundry_cache.get(s_name.lower())
                if not s_obj:
                    row_errors.append(f"Row {row_idx}: Bill Sundry '{s_name}' does not exist. Please create it in Bill Sundry master first.")
                    continue
                s_amt = _parse_decimal(get_val(row, a_col), Decimal("0"))
                existing_ids = {s["bill_sundry"].id for s in grouped[group_key]["sundries"]}
                if s_obj.id not in existing_ids:
                    grouped[group_key]["sundries"].append({"bill_sundry": s_obj, "amount": s_amt})

    if row_errors:
        result["errors"].extend(row_errors)
        return result

    with transaction.atomic():
        for group_key, data in grouped.items():
            vno = data["voucher_no"]
            pr_obj = PurchaseReturn.objects.filter(voucher_no=vno).first() if vno else None
            if pr_obj:
                if update_existing:
                    pr_obj.date = data["date"]
                    pr_obj.account = data["account"]
                    pr_obj.purchase_type = data["purchase_type"]
                    pr_obj.against_purchase = data["against_purchase"]
                    pr_obj.narration = data["narration"]
                    pr_obj.save()
                    pr_obj.items.all().delete()
                    pr_obj.bill_sundries.all().delete()
                    result["vouchers_updated"] += 1
                else:
                    result["vouchers_skipped"] += 1
                    continue
            else:
                pr_obj = PurchaseReturn.objects.create(
                    voucher_no=vno or "",
                    date=data["date"],
                    account=data["account"],
                    purchase_type=data["purchase_type"],
                    against_purchase=data["against_purchase"],
                    narration=data["narration"],
                )
                result["vouchers_created"] += 1

            PurchaseReturnItem.objects.bulk_create([
                PurchaseReturnItem(
                    purchase_return=pr_obj,
                    item=itm["item"],
                    unit=itm["unit"],
                    quantity=itm["quantity"],
                    rate=itm["rate"],
                    discount=itm["discount"],
                    tax=itm["tax"],
                )
                for itm in data["items"]
            ])
            result["items_count"] += len(data["items"])

            for snd in data["sundries"]:
                PurchaseReturnBillSundry.objects.create(
                    purchase_return=pr_obj,
                    bill_sundry=snd["bill_sundry"],
                    amount=snd["amount"],
                )

    result["success"] = bool(result["vouchers_created"] or result["vouchers_updated"] or result["vouchers_skipped"])
    return result


# ==============================================================================
# CREDIT NOTE VOUCHER TEMPLATE & IMPORT
# ==============================================================================

CREDIT_NOTE_VOUCHER_HEADERS = [
    "Date *",
    "Voucher No",
    "Party (Customer) *",
    "Against Sale Invoice",
    "Reason Account *",
    "Amount *",
    "Narration",
]

CREDIT_NOTE_SAMPLE_ROWS = [
    ["2026-09-10", "CN-001", "Apex Infotech Pvt Ltd", "INV-001", "Sales Return", 5000.00, "Price correction after billing"],
    ["", "CN-001", "", "", "Discount Allowed", 500.00, ""],
    ["2026-09-11", "CN-002", "Walk-in Customer", "", "Sales Return", 1200.00, "Damaged goods returned"],
]

CREDIT_NOTE_COLUMN_GUIDE = [
    {"name": "Date *", "type": "Date", "required": True, "description": "Voucher date. Enter on first row of each voucher."},
    {"name": "Voucher No", "type": "Text", "required": False, "description": "Auto-generated (CN-) if left blank."},
    {"name": "Party (Customer) *", "type": "Text", "required": True, "description": "Customer account being credited. Enter on first row; must already exist."},
    {"name": "Against Sale Invoice", "type": "Text", "required": False, "description": "Optional: original sale invoice number this note relates to."},
    {"name": "Reason Account *", "type": "Text", "required": True, "description": "Ledger debited by this line (e.g. 'Sales Return', 'Discount Allowed'). Must already exist."},
    {"name": "Amount *", "type": "Number", "required": True, "description": "Positive amount for this reason line."},
    {"name": "Narration", "type": "Text", "required": False, "description": "Voucher narration; enter on the first row."},
]


def generate_credit_note_template():
    """Generate and return an in-memory .xlsx template for Credit Note import."""
    check_openpyxl()
    from .models import Account, Sale

    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "Credit Notes"
    _apply_header_style(ws, CREDIT_NOTE_VOUCHER_HEADERS, bg_color="1A5276")
    for r in CREDIT_NOTE_SAMPLE_ROWS:
        ws.append(r)
    _auto_adjust_columns(ws)

    ws_acc = wb.create_sheet(title="Existing Accounts")
    _apply_header_style(ws_acc, ["Account Name", "Group"], bg_color="366092")
    for acc in Account.objects.select_related("account_group").order_by("account_name")[:500]:
        ws_acc.append([acc.account_name, acc.account_group.name if acc.account_group else ""])
    _auto_adjust_columns(ws_acc)

    ws_sales = wb.create_sheet(title="Existing Sales (for Against)")
    _apply_header_style(ws_sales, ["Invoice No", "Date", "Party"], bg_color="8E44AD")
    for s in Sale.objects.select_related("account").order_by("-date")[:200]:
        ws_sales.append([s.invoice_no, str(s.date), s.account.account_name])
    _auto_adjust_columns(ws_sales)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def import_credit_notes_from_excel(file_obj, update_existing=False):
    """
    Parse an Excel file and import Credit Note Vouchers.
    Each voucher has one header party (customer being credited) and one or more
    reason-ledger lines (accounts debited, e.g. Sales Return, Discount Allowed).
    No Cash/Bank 'Through' account is involved — the party is a trade debtor.
    """
    check_openpyxl()
    from .models import Account, Sale, CreditNote, CreditNoteLine

    result = _cash_voucher_result()
    loaded, errors = _load_import_rows(file_obj)
    if errors:
        result["errors"] = errors
        return result
    rows, header_map = loaded
    accounts = {a.account_name.lower(): a for a in Account.objects.select_related("account_group").all()}
    sale_cache = {s.invoice_no.lower(): s for s in Sale.objects.all()}
    grouped, row_errors = {}, []

    _last_voucher_no = ""
    _last_raw_date = None
    _last_party_name = ""
    _last_against_str = ""
    _last_narration = ""

    for row_number, row in enumerate(rows, start=2):
        if not any(row):
            continue
        result["total_rows"] += 1

        voucher_no = _clean_str(_row_value(row, header_map, "Voucher No", "voucher_no", "Voucher No *"))
        if not voucher_no:
            voucher_no = _last_voucher_no
        _last_voucher_no = voucher_no

        reason_name = _clean_str(_row_value(row, header_map, "Reason Account *", "Reason Account", "Reason", "Account *", "Account"))
        amount = _parse_decimal(_row_value(row, header_map, "Amount *", "Amount"), Decimal("0"))

        if not reason_name or amount <= 0:
            row_errors.append(f"Row {row_number} ({voucher_no}): 'Reason Account' and a positive 'Amount' are required on every line.")
            continue

        reason_acc = accounts.get(reason_name.lower())
        if not reason_acc:
            row_errors.append(f"Row {row_number} ({voucher_no}): Reason Account '{reason_name}' does not exist.")
            continue

        group_key = voucher_no if voucher_no else f"__auto_{row_number}__"

        if group_key not in grouped:
            party_name = _clean_str(_row_value(row, header_map, "Party (Customer) *", "Party (Customer)", "Party", "Customer"))
            if not party_name:
                party_name = _last_party_name
            else:
                _last_party_name = party_name

            if not party_name:
                row_errors.append(f"Row {row_number} ({group_key}): 'Party (Customer)' is required on the first row of each voucher.")
                continue

            party_acc = accounts.get(party_name.lower())
            if not party_acc:
                row_errors.append(f"Row {row_number} ({group_key}): Party account '{party_name}' does not exist.")
                continue

            raw_date = _row_value(row, header_map, "Date *", "Date")
            if raw_date is None or _clean_str(raw_date) == "":
                raw_date = _last_raw_date
            else:
                _last_raw_date = raw_date
            voucher_date = _parse_date(raw_date)
            if not voucher_date:
                row_errors.append(f"Row {row_number} ({group_key}): a valid Date is required on the first row.")
                continue

            against_str = _clean_str(_row_value(row, header_map, "Against Sale Invoice", "Against Sale", "Against Invoice"))
            if not against_str:
                against_str = _last_against_str
            else:
                _last_against_str = against_str
            against_obj = sale_cache.get(against_str.lower()) if against_str else None

            narration = _clean_str(_row_value(row, header_map, "Narration", "Remarks"))
            if not narration:
                narration = _last_narration
            else:
                _last_narration = narration

            grouped[group_key] = {
                "voucher_no": voucher_no,
                "date": voucher_date,
                "account": party_acc,
                "against_sale": against_obj,
                "narration": narration,
                "lines": [],
            }

        grouped[group_key]["lines"].append({"account": reason_acc, "amount": amount})

    if row_errors:
        result["errors"] = row_errors
        return result

    with transaction.atomic():
        for group_key, data in grouped.items():
            vno = data["voucher_no"]
            cn = CreditNote.objects.filter(voucher_no=vno).first() if vno else None
            if cn:
                if not update_existing:
                    result["vouchers_skipped"] += 1
                    continue
                cn.date = data["date"]
                cn.account = data["account"]
                cn.against_sale = data["against_sale"]
                cn.narration = data["narration"]
                cn.save()
                cn.lines.all().delete()
                result["vouchers_updated"] += 1
            else:
                cn = CreditNote.objects.create(
                    voucher_no=vno or "",
                    date=data["date"],
                    account=data["account"],
                    against_sale=data["against_sale"],
                    narration=data["narration"],
                )
                result["vouchers_created"] += 1
            CreditNoteLine.objects.bulk_create([CreditNoteLine(credit_note=cn, **line) for line in data["lines"]])
            result["items_count"] += len(data["lines"])

    result["success"] = bool(result["vouchers_created"] or result["vouchers_updated"] or result["vouchers_skipped"])
    return result


# ==============================================================================
# DEBIT NOTE VOUCHER TEMPLATE & IMPORT
# ==============================================================================

DEBIT_NOTE_VOUCHER_HEADERS = [
    "Date *",
    "Voucher No",
    "Party (Supplier) *",
    "Against Purchase Invoice",
    "Reason Account *",
    "Amount *",
    "Narration",
]

DEBIT_NOTE_SAMPLE_ROWS = [
    ["2026-09-10", "DN-001", "National Steel Corporation", "PUR-501", "Purchase Return", 4800.00, "Shortage deduction"],
    ["", "DN-001", "", "", "Discount Received", 200.00, ""],
    ["2026-09-11", "DN-002", "National Steel Corporation", "", "Purchase Return", 9600.00, "Returned excess stock"],
]

DEBIT_NOTE_COLUMN_GUIDE = [
    {"name": "Date *", "type": "Date", "required": True, "description": "Voucher date. Enter on first row of each voucher."},
    {"name": "Voucher No", "type": "Text", "required": False, "description": "Auto-generated (DN-) if left blank."},
    {"name": "Party (Supplier) *", "type": "Text", "required": True, "description": "Supplier account being debited. Enter on first row; must already exist."},
    {"name": "Against Purchase Invoice", "type": "Text", "required": False, "description": "Optional: original purchase invoice number this note relates to."},
    {"name": "Reason Account *", "type": "Text", "required": True, "description": "Ledger credited by this line (e.g. 'Purchase Return', 'Discount Received'). Must already exist."},
    {"name": "Amount *", "type": "Number", "required": True, "description": "Positive amount for this reason line."},
    {"name": "Narration", "type": "Text", "required": False, "description": "Voucher narration; enter on the first row."},
]


def generate_debit_note_template():
    """Generate and return an in-memory .xlsx template for Debit Note import."""
    check_openpyxl()
    from .models import Account, Purchase

    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "Debit Notes"
    _apply_header_style(ws, DEBIT_NOTE_VOUCHER_HEADERS, bg_color="641E16")
    for r in DEBIT_NOTE_SAMPLE_ROWS:
        ws.append(r)
    _auto_adjust_columns(ws)

    ws_acc = wb.create_sheet(title="Existing Accounts")
    _apply_header_style(ws_acc, ["Account Name", "Group"], bg_color="366092")
    for acc in Account.objects.select_related("account_group").order_by("account_name")[:500]:
        ws_acc.append([acc.account_name, acc.account_group.name if acc.account_group else ""])
    _auto_adjust_columns(ws_acc)

    ws_pur = wb.create_sheet(title="Existing Purchases (for Against)")
    _apply_header_style(ws_pur, ["Invoice No", "Date", "Supplier"], bg_color="117A65")
    for p in Purchase.objects.select_related("account").order_by("-date")[:200]:
        ws_pur.append([p.invoice_no, str(p.date), p.account.account_name])
    _auto_adjust_columns(ws_pur)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def import_debit_notes_from_excel(file_obj, update_existing=False):
    """
    Parse an Excel file and import Debit Note Vouchers.
    Each voucher has one header party (supplier being debited) and one or more
    reason-ledger lines (accounts credited, e.g. Purchase Return, Discount Received).
    No Cash/Bank 'Through' account is involved — the party is a trade creditor.
    """
    check_openpyxl()
    from .models import Account, Purchase, DebitNote, DebitNoteLine

    result = _cash_voucher_result()
    loaded, errors = _load_import_rows(file_obj)
    if errors:
        result["errors"] = errors
        return result
    rows, header_map = loaded
    accounts = {a.account_name.lower(): a for a in Account.objects.select_related("account_group").all()}
    purchase_cache = {p.invoice_no.lower(): p for p in Purchase.objects.all()}
    grouped, row_errors = {}, []

    _last_voucher_no = ""
    _last_raw_date = None
    _last_party_name = ""
    _last_against_str = ""
    _last_narration = ""

    for row_number, row in enumerate(rows, start=2):
        if not any(row):
            continue
        result["total_rows"] += 1

        voucher_no = _clean_str(_row_value(row, header_map, "Voucher No", "voucher_no", "Voucher No *"))
        if not voucher_no:
            voucher_no = _last_voucher_no
        _last_voucher_no = voucher_no

        reason_name = _clean_str(_row_value(row, header_map, "Reason Account *", "Reason Account", "Reason", "Account *", "Account"))
        amount = _parse_decimal(_row_value(row, header_map, "Amount *", "Amount"), Decimal("0"))

        if not reason_name or amount <= 0:
            row_errors.append(f"Row {row_number} ({voucher_no}): 'Reason Account' and a positive 'Amount' are required on every line.")
            continue

        reason_acc = accounts.get(reason_name.lower())
        if not reason_acc:
            row_errors.append(f"Row {row_number} ({voucher_no}): Reason Account '{reason_name}' does not exist.")
            continue

        group_key = voucher_no if voucher_no else f"__auto_{row_number}__"

        if group_key not in grouped:
            party_name = _clean_str(_row_value(row, header_map, "Party (Supplier) *", "Party (Supplier)", "Party", "Supplier"))
            if not party_name:
                party_name = _last_party_name
            else:
                _last_party_name = party_name

            if not party_name:
                row_errors.append(f"Row {row_number} ({group_key}): 'Party (Supplier)' is required on the first row of each voucher.")
                continue

            party_acc = accounts.get(party_name.lower())
            if not party_acc:
                row_errors.append(f"Row {row_number} ({group_key}): Party account '{party_name}' does not exist.")
                continue

            raw_date = _row_value(row, header_map, "Date *", "Date")
            if raw_date is None or _clean_str(raw_date) == "":
                raw_date = _last_raw_date
            else:
                _last_raw_date = raw_date
            voucher_date = _parse_date(raw_date)
            if not voucher_date:
                row_errors.append(f"Row {row_number} ({group_key}): a valid Date is required on the first row.")
                continue

            against_str = _clean_str(_row_value(row, header_map, "Against Purchase Invoice", "Against Purchase", "Against Invoice"))
            if not against_str:
                against_str = _last_against_str
            else:
                _last_against_str = against_str
            against_obj = purchase_cache.get(against_str.lower()) if against_str else None

            narration = _clean_str(_row_value(row, header_map, "Narration", "Remarks"))
            if not narration:
                narration = _last_narration
            else:
                _last_narration = narration

            grouped[group_key] = {
                "voucher_no": voucher_no,
                "date": voucher_date,
                "account": party_acc,
                "against_purchase": against_obj,
                "narration": narration,
                "lines": [],
            }

        grouped[group_key]["lines"].append({"account": reason_acc, "amount": amount})

    if row_errors:
        result["errors"] = row_errors
        return result

    with transaction.atomic():
        for group_key, data in grouped.items():
            vno = data["voucher_no"]
            dn = DebitNote.objects.filter(voucher_no=vno).first() if vno else None
            if dn:
                if not update_existing:
                    result["vouchers_skipped"] += 1
                    continue
                dn.date = data["date"]
                dn.account = data["account"]
                dn.against_purchase = data["against_purchase"]
                dn.narration = data["narration"]
                dn.save()
                dn.lines.all().delete()
                result["vouchers_updated"] += 1
            else:
                dn = DebitNote.objects.create(
                    voucher_no=vno or "",
                    date=data["date"],
                    account=data["account"],
                    against_purchase=data["against_purchase"],
                    narration=data["narration"],
                )
                result["vouchers_created"] += 1
            DebitNoteLine.objects.bulk_create([DebitNoteLine(debit_note=dn, **line) for line in data["lines"]])
            result["items_count"] += len(data["lines"])

    result["success"] = bool(result["vouchers_created"] or result["vouchers_updated"] or result["vouchers_skipped"])
    return result


def import_journals_from_excel(file_obj, update_existing=False):
    check_openpyxl()
    from .models import Account, Journal, JournalLine

    result = _cash_voucher_result()
    loaded, errors = _load_import_rows(file_obj)
    if errors:
        result["errors"] = errors
        return result
    rows, header_map = loaded
    accounts = {account.account_name.lower(): account for account in Account.objects.all()}
    grouped, row_errors = {}, []

    # Carry-forward state for multi-line vouchers (Busy / Tally export style).
    _last_voucher_no = ""
    _last_raw_date = None
    _last_narration = ""

    for row_number, row in enumerate(rows, start=2):
        if not any(row):
            continue
        result["total_rows"] += 1

        voucher_no = _clean_str(_row_value(row, header_map, "Voucher No *", "Voucher No", "voucher_no"))
        if not voucher_no:
            voucher_no = _last_voucher_no
        if not voucher_no:
            row_errors.append(f"Row {row_number}: 'Voucher No' is required.")
            continue
        _last_voucher_no = voucher_no

        account_name = _clean_str(_row_value(row, header_map, "Account *", "Account"))
        debit = _parse_decimal(_row_value(row, header_map, "Debit", "Dr"), Decimal("0"))
        credit = _parse_decimal(_row_value(row, header_map, "Credit", "Cr"), Decimal("0"))
        account = accounts.get(account_name.lower())
        if not account:
            row_errors.append(f"Row {row_number} ({voucher_no}): Account '{account_name}' is required and must exist.")
            continue
        if debit < 0 or credit < 0 or (debit and credit) or (not debit and not credit):
            row_errors.append(f"Row {row_number} ({voucher_no}): enter a positive Debit or Credit, not both.")
            continue

        if voucher_no not in grouped:
            raw_date = _row_value(row, header_map, "Date *", "Date")
            if raw_date is None or _clean_str(raw_date) == "":
                raw_date = _last_raw_date
            else:
                _last_raw_date = raw_date
            voucher_date = _parse_date(raw_date)
            if not voucher_date:
                row_errors.append(f"Row {row_number} ({voucher_no}): a valid Date is required on the first row.")
                continue

            narration = _clean_str(_row_value(row, header_map, "Narration"))
            if not narration:
                narration = _last_narration
            else:
                _last_narration = narration

            grouped[voucher_no] = {"date": voucher_date, "narration": narration, "lines": []}
        grouped[voucher_no]["lines"].append({"account": account, "debit": debit, "credit": credit, "remarks": _clean_str(_row_value(row, header_map, "Remarks", "Remark"))})

    for voucher_no, data in grouped.items():
        debit_total = sum((line["debit"] for line in data["lines"]), Decimal("0"))
        credit_total = sum((line["credit"] for line in data["lines"]), Decimal("0"))
        if len(data["lines"]) < 2 or debit_total != credit_total:
            row_errors.append(f"Voucher {voucher_no}: needs at least two lines and equal Debit/Credit totals.")
    if row_errors:
        result["errors"] = row_errors
        return result
    with transaction.atomic():
        for voucher_no, data in grouped.items():
            voucher = Journal.objects.filter(voucher_no=voucher_no).first()
            if voucher and not update_existing:
                result["vouchers_skipped"] += 1
                continue
            if voucher:
                voucher.date, voucher.narration = data["date"], data["narration"]
                voucher.save()
                voucher.lines.all().delete()
                result["vouchers_updated"] += 1
            else:
                voucher = Journal.objects.create(voucher_no=voucher_no, date=data["date"], narration=data["narration"])
                result["vouchers_created"] += 1
            JournalLine.objects.bulk_create([JournalLine(journal=voucher, **line) for line in data["lines"]])
            result["items_count"] += len(data["lines"])
    result["success"] = bool(result["vouchers_created"] or result["vouchers_updated"] or result["vouchers_skipped"])
    return result
