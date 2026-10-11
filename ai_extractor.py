"""Optional Gemini vision fallback for complex invoice and receipt documents."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pdf2image import convert_from_path
from PIL import Image

from ocr_reader import _find_poppler_path

MODEL_NAME = "gemini-3.8-flash"
AI_KEYS = {
    "invoice_number": "Invoice Number",
    "invoice_date": "Invoice Date",
    "vendor_name": "Vendor/Company Name",
    "subtotal": "Subtotal",
    "tax_amount": "Tax Amount",
    "grand_total": "Grand Total",
    "currency": "Currency",
}
PROMPT = (
    "Extract from this invoice/receipt: invoice_number, "
    "invoice_date (YYYY-MM-DD), vendor_name, subtotal, tax_amount, "
    "grand_total, currency. Return ONLY a JSON object with these keys, "
    "null for anything not found.\n"
    "Amount rules: subtotal is the net amount before tax; tax_amount is "
    "the tax or VAT value; grand_total is the final amount the customer pays. "
    "grand_total MUST come from a value labeled Total, Grand Total, Gross Total, "
    "Amount Due, or Payable — NEVER use subtotal, net amount, or net worth as "
    "grand_total. If multiple eligible totals exist, grand_total must be the "
    "LARGEST final amount on the document. Return amounts as plain numbers "
    "(for example 149.60, not $149,60).\n\n"
    "Raw OCR text for context:\n"
)


def _field_names() -> tuple[str, ...]:
    """Resolve field names lazily to avoid a cycle with extractor.py."""
    from extractor import FIELD_NAMES

    return FIELD_NAMES


def is_ai_configured() -> bool:
    """Return whether a Gemini API key is available in the environment."""
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def _document_images(path: Path) -> list[Image.Image]:
    """Load supported source documents as RGB images for Gemini vision."""
    if path.suffix.lower() == ".pdf":
        return [
            page.convert("RGB")
            for page in convert_from_path(
                path, dpi=180, poppler_path=_find_poppler_path()
            )
        ]

    with Image.open(path) as image:
        return [image.convert("RGB")]


def _normalize_date(value: Any) -> str:
    """Normalize common model date outputs to YYYY-MM-DD."""
    if not isinstance(value, str) or not value.strip():
        return "N/A"
    value = value.strip()
    for date_format in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(value, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return "N/A"


def _normalize_amount(value: Any) -> float | str:
    """Convert Gemini numeric or formatted amounts to Excel-friendly numbers."""
    if isinstance(value, bool) or value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return "N/A"

    cleaned = re.sub(r"[^0-9,.\-()]", "", value).replace(",", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    try:
        amount = float(cleaned)
    except ValueError:
        return "N/A"
    return -amount if negative else amount


def _parse_response(response_text: str) -> dict[str, Any]:
    """Decode the JSON object and map only valid values to our field names."""
    start = response_text.find("{")
    if start < 0:
        raise ValueError("Gemini response did not contain a JSON object.")
    payload, _ = json.JSONDecoder().raw_decode(response_text[start:])
    if not isinstance(payload, dict):
        raise ValueError("Gemini response JSON was not an object.")

    result = {field: "N/A" for field in _field_names()}
    for source_key, field_name in AI_KEYS.items():
        value = payload.get(source_key)
        if source_key in ("subtotal", "tax_amount", "grand_total"):
            result[field_name] = _normalize_amount(value)
        elif source_key == "invoice_date":
            result[field_name] = _normalize_date(value)
        elif source_key == "currency":
            if isinstance(value, str) and value.strip():
                result[field_name] = value.strip().upper()
        elif isinstance(value, str) and value.strip():
            result[field_name] = value.strip()
        elif source_key == "invoice_number" and isinstance(value, (int, float)):
            result[field_name] = str(value)

    return result


def extract_with_ai(
    image_or_pdf_path: str | Path, ocr_text: str
) -> dict[str, Any]:
    """Extract invoice fields with Gemini vision; return N/A fields on any failure."""
    empty_result = {field: "N/A" for field in _field_names()}
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return empty_result

    images: list[Image.Image] = []
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        images = _document_images(Path(image_or_pdf_path))
        if not images:
            raise ValueError("Document contained no pages to send for extraction.")

        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(
            [PROMPT + (ocr_text or "(No usable OCR text was extracted.)"), *images],
            generation_config={"response_mime_type": "application/json"},
        )
        response_text = getattr(response, "text", None)
        if not response_text:
            raise ValueError("Gemini returned an empty response.")
        result = _parse_response(response_text)
        for field, value in result.items():
            if isinstance(value, str) and api_key in value:
                result[field] = "N/A"
        print(f"AI extraction succeeded for '{Path(image_or_pdf_path).name}'.")
        return result
    except Exception:
        print(f"AI extraction failed for '{Path(image_or_pdf_path).name}'.")
        return empty_result
    finally:
        for image in images:
            image.close()
