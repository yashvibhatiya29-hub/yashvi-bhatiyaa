"""
gst_parser.py - reads the GST rate CSV and returns clean, validated data.

It handles:
  * messy headers   "HSN Code", "GST Rate (%)", "Item Name", "SGST/UTGST" ...
  * rate text       "18%", "18 %", "9+9", "Nil", "Exempt", "2.5"
  * HSN/SAC codes   kept as text (leading zeros survive), dots/spaces removed,
                    a zero dropped by Excel is restored (401 -> 0401)
  * missing split   IGST only -> CGST = SGST = IGST / 2, or CGST+SGST -> IGST
  * checks          CGST + SGST must equal IGST, unusual or retired slabs,
                    duplicates, rows without a name, "Verified" rows that
                    carry no official evidence
"""

import io
import re

import pandas as pd

COLUMNS = [
    "product_id", "item_type", "product_name", "keywords", "description", "category",
    "hsn_code", "cgst_rate", "sgst_rate", "igst_rate", "cess_rate", "tax_status",
    "notification_number", "notification_date", "effective_from",
    "official_source", "source_url", "verification_date", "verification_status", "remarks",
]
RATE_COLUMNS = ["cgst_rate", "sgst_rate", "igst_rate", "cess_rate"]
ISSUE_COLUMNS = ["row", "column", "level", "message"]

# GST 2.0 slabs (from 22-Sep-2025) plus special rates.
STANDARD_SLABS = {0.0, 0.1, 0.25, 1.5, 3.0, 5.0, 18.0, 40.0}
RETIRED_SLABS = {12.0, 28.0}

HEADER_ALIASES = {
    "id": "product_id", "sr_no": "product_id", "s_no": "product_id", "sl_no": "product_id",
    "type": "item_type", "goods_or_service": "item_type",
    "product": "product_name", "name": "product_name", "item": "product_name",
    "item_name": "product_name", "goods": "product_name",
    "description_of_goods": "description",
    "synonyms": "keywords", "aliases": "keywords", "tags": "keywords",
    "hsn": "hsn_code", "hsn_sac": "hsn_code", "hsn_sac_code": "hsn_code", "sac": "hsn_code",
    "sac_code": "hsn_code", "hsn_no": "hsn_code", "chapter_heading": "hsn_code",
    "tariff_item": "hsn_code",
    "cgst": "cgst_rate", "central_tax": "cgst_rate", "central_tax_rate": "cgst_rate",
    "sgst": "sgst_rate", "utgst": "sgst_rate", "sgst_utgst": "sgst_rate",
    "sgst_utgst_rate": "sgst_rate", "state_tax": "sgst_rate", "state_tax_rate": "sgst_rate",
    "igst": "igst_rate", "integrated_tax": "igst_rate", "integrated_tax_rate": "igst_rate",
    "gst": "igst_rate", "gst_rate": "igst_rate", "rate": "igst_rate",
    "total_gst": "igst_rate", "tax_rate": "igst_rate",
    "cess": "cess_rate", "compensation_cess": "cess_rate",
    "status": "verification_status", "verified": "verification_status",
    "notification": "notification_number", "notification_no": "notification_number",
    "source": "official_source", "url": "source_url", "link": "source_url",
}

NIL_WORDS = {"nil", "exempt", "exempted", "zero", "free"}
BLANK_WORDS = {"", "-", "--", "na", "n/a", "none", "nan"}
YES_WORDS = {"verified", "yes", "y", "true", "1"}


def normalize_header(name):
    """'GST Rate (%)' -> 'igst_rate', 'HSN/SAC' -> 'hsn_code'."""
    text = str(name).strip().lower().replace("%", "")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return HEADER_ALIASES.get(text, text)


def parse_rate(value):
    """'18%' -> 18.0, 'Nil' -> 0.0, '9+9' -> 18.0, '' -> None. Raises ValueError on junk."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if pd.isna(value):
            return None
        number = float(value)
    else:
        text = str(value).strip().lower()
        for word in ("%", "per cent", "percent"):
            text = text.replace(word, "")
        text = text.strip()
        if text in BLANK_WORDS:
            return None
        if text in NIL_WORDS:
            return 0.0
        if "+" in text:
            return sum(parse_rate(part) or 0.0 for part in text.split("+"))
        try:
            number = float(text)
        except ValueError:
            raise ValueError(f"cannot read rate '{value}'")
    if not 0 <= number <= 100:
        raise ValueError(f"rate {number:g} is outside 0-100")
    return number


def clean_hsn(value):
    """Keep HSN as text: '401.0' -> '0401', '0401 10' -> '040110'."""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    text = re.sub(r"[\s.\-]", "", text)
    if text.isdigit() and len(text) % 2 == 1:
        text = "0" + text
    return text


def _read_raw(source):
    """Read a path, bytes or uploaded file into an all-text DataFrame."""
    if hasattr(source, "read"):
        data = source.read()
    elif isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        with open(source, "rb") as f:
            data = f.read()
    if isinstance(data, str):
        data = data.encode("utf-8")

    text = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text or not text.strip():
        return pd.DataFrame(columns=COLUMNS)

    def read(sep):
        return pd.read_csv(io.StringIO(text), sep=sep, dtype=str,
                           keep_default_na=False, skipinitialspace=True)

    frame = read(",")
    first_line = text.splitlines()[0]
    if frame.shape[1] == 1:  # maybe semicolon or tab separated
        for sep in (";", "\t"):
            if sep in first_line:
                frame = read(sep)
                break
    return frame


def parse_gst_csv(source):
    """Parse a GST CSV. Returns (clean DataFrame, issues DataFrame, summary dict)."""
    issues = []

    def note(row, column, level, message):
        issues.append({"row": str(row), "column": column, "level": level, "message": message})

    raw = _read_raw(source)
    raw.columns = [normalize_header(c) for c in raw.columns]
    raw = raw.loc[:, ~raw.columns.duplicated()]

    if len(raw) and "product_name" not in raw.columns:
        note("header", "product_name", "error", "No product name column found")
    unknown = [c for c in raw.columns if c not in COLUMNS]
    if unknown:
        note("header", ", ".join(unknown), "info", "Columns not used by the app were ignored")
    for column in COLUMNS:
        if column not in raw.columns:
            raw[column] = ""
    raw = raw[COLUMNS]

    records, seen = [], set()
    fixes = 0
    for index, row in raw.iterrows():
        line = index + 2  # line number in the CSV (line 1 is the header)
        rec = {c: str(row[c]).strip() for c in COLUMNS}
        if not any(rec.values()):
            continue
        if not rec["product_name"]:
            note(line, "product_name", "error", "No product name - row skipped")
            continue
        outside = "outside" in rec["tax_status"].lower()

        rates = {}
        for column in RATE_COLUMNS:
            try:
                rates[column] = parse_rate(rec[column])
            except ValueError as err:
                note(line, column, "error", str(err))
                rates[column] = None
        cgst, sgst, igst = rates["cgst_rate"], rates["sgst_rate"], rates["igst_rate"]

        if igst is None and cgst is None and sgst is None:
            if not outside:
                note(line, "igst_rate", "warning", "No GST rate given")
        elif igst is None:
            cgst = cgst if cgst is not None else sgst
            sgst = sgst if sgst is not None else cgst
            igst = cgst + sgst
            fixes += 1
            note(line, "igst_rate", "info", f"IGST filled as CGST + SGST = {igst:g}%")
        elif cgst is None or sgst is None:
            cgst = sgst = igst / 2
            fixes += 1
            note(line, "cgst_rate", "info", f"CGST and SGST filled as IGST / 2 = {cgst:g}%")
        elif abs(cgst + sgst - igst) > 0.001:
            note(line, "igst_rate", "warning",
                 f"CGST {cgst:g}% + SGST {sgst:g}% does not equal IGST {igst:g}%")

        if igst is not None:
            if igst in RETIRED_SLABS:
                note(line, "igst_rate", "warning",
                     f"{igst:g}% slab was largely replaced on 22-Sep-2025 - check the effective date")
            elif igst not in STANDARD_SLABS:
                note(line, "igst_rate", "warning", f"{igst:g}% is not a usual GST slab")

        hsn = clean_hsn(rec["hsn_code"])
        if not hsn:
            note(line, "hsn_code", "warning", "No HSN / SAC code")
        elif not hsn.isdigit():
            note(line, "hsn_code", "warning", f"HSN '{hsn}' is not numeric")
        elif hsn != rec["hsn_code"]:
            fixes += 1
            note(line, "hsn_code", "info", f"HSN '{rec['hsn_code']}' cleaned to '{hsn}'")

        status = rec["verification_status"]
        if status.lower() in YES_WORDS:
            status = "Verified"
            if not (rec["notification_number"] or rec["source_url"]):
                status = "Needs evidence"
                note(line, "verification_status", "warning",
                     "Marked Verified but has no notification number or source URL")
        else:
            status = status.title() if status else "Pending"

        tax_status = rec["tax_status"]
        if not tax_status and igst is not None:
            tax_status = "Nil rated / Exempt" if igst == 0 else "Taxable"

        item_type = rec["item_type"].title()
        if item_type not in ("Goods", "Service"):
            item_type = "Service" if hsn.startswith("99") else "Goods"

        key = (rec["product_name"].lower(), hsn)
        if key in seen:
            note(line, "product_name", "warning", "Duplicate name and HSN")
        seen.add(key)

        rec.update({
            "product_id": rec["product_id"] or f"P{len(records) + 1:03d}",
            "item_type": item_type,
            "keywords": rec["keywords"].lower(),
            "hsn_code": hsn,
            "cgst_rate": cgst, "sgst_rate": sgst, "igst_rate": igst,
            "cess_rate": rates["cess_rate"] or (None if outside else 0.0),
            "tax_status": tax_status,
            "verification_status": status,
        })
        records.append(rec)

    df = pd.DataFrame(records, columns=COLUMNS)
    for column in RATE_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    issues_df = pd.DataFrame(issues, columns=ISSUE_COLUMNS)
    summary = {
        "rows_read": int(len(raw)),
        "rows_loaded": int(len(df)),
        "fixes": fixes,
        "warnings": int((issues_df["level"] == "warning").sum()),
        "errors": int((issues_df["level"] == "error").sum()),
    }
    return df, issues_df, summary


def template_csv():
    """Blank CSV with the expected header and one example row."""
    example = {c: "" for c in COLUMNS}
    example.update({
        "product_id": "G001", "item_type": "Goods", "product_name": "Example item",
        "keywords": "synonym one, synonym two", "category": "Example",
        "hsn_code": "0401", "igst_rate": "5", "cess_rate": "0",
        "notification_number": "9/2025-Central Tax (Rate) - Schedule I (5%)",
        "verification_status": "Pending",
    })
    return pd.DataFrame([example], columns=COLUMNS).to_csv(index=False)
