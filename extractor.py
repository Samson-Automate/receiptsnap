"""Extract common invoice fields from text-based PDF invoices."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

import pdfplumber

from ai_extractor import extract_with_ai, is_ai_configured
from ocr_reader import extract_text_from_image
from ocr_reader import extract_text_from_scanned_pdf


# Keep this order in sync with the Excel report columns.
FIELD_NAMES = (
    "Invoice Number",
    "Invoice Date",
    "Vendor/Company Name",
    "Subtotal",
    "Tax Amount",
    "Grand Total",
    "Currency",
)
EXTRACTION_METHOD_COLUMN = "Extraction Method"
SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

_DATE_PATTERN = (
    r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"
    r"|\d{1,2}[-/. ]+[A-Za-z]{3,9}[-/. ,]+\d{4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
)
_MONEY_PATTERN = (
    r"\(?\s*(?:(?:[$€£¥₹])|(?:USD|EUR|GBP|CAD|AUD|JPY|INR|CHF|CNY))?"
    r"\s*-?\s*(?:"
    r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"
    r"|\d{1,3}(?:\.\d{3})+,\d{1,2}"
    r"|\d+(?:[.,]\d{1,2})?"
    r")\s*\)?"
)


def extract_text(pdf_path: str | Path) -> str:
    """Use PDF text first, then OCR image-only pages when no text layer exists."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
    except Exception as error:
        print(
            f"Warning: Could not extract text directly from "
            f"'{Path(pdf_path).name}': {error}"
        )
        text = ""

    if not text:
        print(f"No text layer in '{Path(pdf_path).name}'; trying OCR.")
        try:
            text = extract_text_from_scanned_pdf(pdf_path)
        except Exception as error:
            print(f"Warning: OCR failed for '{Path(pdf_path).name}': {error}")
            return ""
        if not text:
            print(f"Warning: OCR found no text in '{Path(pdf_path).name}'.")
    return text


def _find_labeled_value(text: str, labels: str, value_pattern: str) -> str | None:
    """Find a value on the same line as one of its case-insensitive labels."""
    match = re.search(
        rf"^\s*(?:{labels})\s*(?:[:#-]\s*)?({value_pattern})",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return match.group(1).strip() if match else None


def _parse_amount(value: str | None) -> float | str:
    """Convert a captured money amount into an Excel-friendly number."""
    if not value:
        return "N/A"

    cleaned = value.strip().replace(" ", "")
    is_negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    cleaned = re.sub(r"^(?:[$€£¥₹]|USD|EUR|GBP|CAD|AUD|JPY|INR|CHF|CNY)", "", cleaned, flags=re.I)
    if "," in cleaned and "." in cleaned:
        # The final separator is the decimal mark in either common locale format.
        decimal_separator = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        cleaned = cleaned.replace(thousands_separator, "").replace(
            decimal_separator, "."
        )
    elif re.search(r",\d{2}$", cleaned):
        # A trailing two-digit comma with no period is a European decimal mark.
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        amount = float(cleaned)
    except ValueError:
        return "N/A"
    return -amount if is_negative else amount


def _find_vendor(text: str) -> str:
    """Use the first plausible company/header line as the vendor name."""
    excluded = re.compile(
        r"^(?:invoice|tax invoice|receipt|bill to|ship to|date|invoice date|"
        r"invoice number|invoice no\.?|number|www\.|https?://)",
        re.IGNORECASE,
    )
    for line in text.splitlines()[:12]:
        candidate = " ".join(line.split()).strip(" -:")
        if (
            candidate
            and not excluded.search(candidate)
            and not re.fullmatch(r"[\d\s/#:.,-]+", candidate)
            and len(candidate) <= 100
        ):
            return candidate
    return "N/A"


def _has_invoice_signals(text: str) -> bool:
    """Reject unstructured poster text that otherwise looks like a vendor header."""
    labels = (
        r"invoice|tax\s+invoice|receipt|bill|invoice\s*(?:number|no\.?|#)|"
        r"inv\.?\s*(?:no\.?|#)|sub\s*total|subtotal|(?:sales\s*)?tax|VAT|GST|"
        r"grand\s*total|gross\s*total|total(?:\s*(?:due|amount))?|"
        r"amount\s*due|balance\s*due|payable"
    )
    if re.search(
        rf"^\s*(?:{labels})\s*(?:[:#-]|\b)",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    ):
        return True
    return bool(
        re.search(
            rf"^\s*date\s*[:#-]\s*{_DATE_PATTERN}",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    )


def _find_currency(text: str) -> str:
    """Detect a currency marker only when it is directly beside an amount."""
    currency_codes = {
        "USD": "USD",
        "EUR": "EUR",
        "GBP": "GBP",
        "CAD": "CAD",
        "AUD": "AUD",
        "JPY": "JPY",
        "INR": "INR",
        "NZD": "NZD",
        "CHF": "CHF",
        "CNY": "CNY",
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "¥": "JPY",
        "₹": "INR",
    }
    marker_pattern = "|".join(
        re.escape(marker)
        for marker in sorted(currency_codes, key=len, reverse=True)
    )
    amount_pattern = (
        r"(?:"
        r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"
        r"|\d{1,3}(?:\.\d{3})+,\d{1,2}"
        r"|\d+(?:[.,]\d{1,2})?"
        r")"
    )
    currency_amount = re.compile(
        rf"(?<![A-Za-z])(?P<before>{marker_pattern})(?![A-Za-z])\s*"
        rf"-?{amount_pattern}(?![\d.,])"
        rf"|(?<![\d.,])-?{amount_pattern}\s*"
        rf"(?P<after>{marker_pattern})(?![A-Za-z])",
        re.IGNORECASE,
    )
    match = currency_amount.search(text)
    if match:
        marker = match.group("before") or match.group("after")
        return currency_codes[marker.upper()] if marker.isalpha() else currency_codes[marker]
    return "N/A"


def _has_amount_consistency_issues(fields: dict[str, Any]) -> bool:
    """Flag impossible or suspicious relationships between parsed amounts."""
    subtotal = fields.get("Subtotal")
    tax = fields.get("Tax Amount")
    grand_total = fields.get("Grand Total")

    numeric_subtotal = isinstance(subtotal, (int, float))
    numeric_tax = isinstance(tax, (int, float))
    numeric_total = isinstance(grand_total, (int, float))

    return (
        (numeric_subtotal and subtotal < 0)
        or (numeric_tax and tax < 0)
        or (numeric_total and grand_total < 0)
        or (
            numeric_subtotal
            and numeric_total
            and grand_total < subtotal
        )
        or (
            numeric_tax
            and numeric_total
            and tax > grand_total
        )
    )


def parse_fields(text: str) -> dict[str, Any]:
    """Parse invoice fields and flag results missing a date or grand total."""
    if not text.strip():
        return {
            **{field: "N/A" for field in FIELD_NAMES},
            EXTRACTION_METHOD_COLUMN: "Needs review",
        }
    if not _has_invoice_signals(text):
        return {
            **{field: "N/A" for field in FIELD_NAMES},
            EXTRACTION_METHOD_COLUMN: "Needs review",
        }

    invoice_number = _find_labeled_value(
        text,
        r"(?:invoice\s*(?:number|no\.?|#)|inv\.?\s*(?:no\.?|#))",
        r"[A-Z0-9][A-Z0-9/_-]*",
    )
    invoice_date = _find_labeled_value(
        text,
        r"(?:invoice\s*date|date)",
        _DATE_PATTERN,
    )

    values: dict[str, Any] = {
        "Invoice Number": invoice_number or "N/A",
        "Invoice Date": invoice_date or "N/A",
        "Vendor/Company Name": _find_vendor(text),
        "Subtotal": _parse_amount(
            _find_labeled_value(text, r"sub\s*total|subtotal", _MONEY_PATTERN)
        ),
        "Tax Amount": _parse_amount(
            _find_labeled_value(
                text, r"(?:sales\s*)?tax(?:\s*amount)?|VAT|GST", _MONEY_PATTERN
            )
        ),
        "Grand Total": _parse_amount(
            _find_labeled_value(
                text,
                r"grand\s*total|total\s*(?:due|amount)?|amount\s*due|balance\s*due",
                _MONEY_PATTERN,
            )
        ),
    }
    has_amount = any(
        isinstance(values[field], (int, float))
        for field in ("Subtotal", "Tax Amount", "Grand Total")
    )
    values["Currency"] = _find_currency(text) if has_amount else "N/A"

    # Guarantee a value in every cell, even if a capture was malformed.
    parsed = {
        field: values.get(field) if values.get(field) not in (None, "") else "N/A"
        for field in FIELD_NAMES
    }
    parsed[EXTRACTION_METHOD_COLUMN] = (
        "Needs review"
        if (
            parsed["Grand Total"] == "N/A"
            or parsed["Invoice Date"] == "N/A"
            or _has_amount_consistency_issues(parsed)
        )
        else "OCR"
    )
    return parsed


def extract_document_fields(
    document_path: str | Path,
    diagnostic: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run local extraction first and use Gemini only when key fields are missing."""
    path = Path(document_path)
    if path.suffix.lower() == ".pdf":
        text = extract_text(path)
    elif path.suffix.lower() in SUPPORTED_EXTENSIONS:
        text = extract_text_from_image(path)
    else:
        raise ValueError(f"Unsupported document format: {path.suffix or '(no extension)'}")

    fields = parse_fields(text)
    weak_result = (
        fields["Grand Total"] == "N/A" or fields["Invoice Date"] == "N/A"
    )
    if not weak_result:
        if diagnostic:
            diagnostic(f"AI skipped for {path.name}: local extraction is complete.")
        return fields

    ai_configured = is_ai_configured()
    if diagnostic:
        diagnostic(f"GEMINI_API_KEY found: {'yes' if ai_configured else 'no'}")
    if not ai_configured:
        if diagnostic:
            diagnostic(f"AI skipped for {path.name}: GEMINI_API_KEY is not set.")
        fields["_AI fallback attempted"] = False
        return fields

    if diagnostic:
        diagnostic(f"AI fallback triggered for {path.name}")
    ai_fields = extract_with_ai(path, text)
    fields["_AI fallback attempted"] = True
    for field in FIELD_NAMES:
        if fields[field] == "N/A" and ai_fields.get(field) not in (None, "", "N/A"):
            fields[field] = ai_fields[field]

    if (
        fields["Grand Total"] != "N/A"
        and fields["Invoice Date"] != "N/A"
        and not _has_amount_consistency_issues(fields)
    ):
        fields[EXTRACTION_METHOD_COLUMN] = "AI-assisted"
    elif _has_amount_consistency_issues(fields):
        fields[EXTRACTION_METHOD_COLUMN] = "Needs review"
    return fields
