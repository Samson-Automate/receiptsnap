"""Batch-process PDFs and receipt images in test_files into an Excel report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from excel_writer import write_excel
from extractor import (
    EXTRACTION_METHOD_COLUMN,
    FIELD_NAMES,
    extract_document_fields,
)

PROJECT_DIR = Path(__file__).resolve().parent
INPUT_DIR = PROJECT_DIR / "test_files"
OUTPUT_DIR = PROJECT_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "invoices.xlsx"


SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def process_invoices(input_dir: Path = INPUT_DIR) -> list[dict[str, Any]]:
    """Extract each supported file independently so one bad file cannot stop the batch."""
    invoice_files = []
    if input_dir.is_dir():
        invoice_files = sorted(
            path
            for path in input_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )
    if not invoice_files:
        print(f"No PDF or image invoices found in '{input_dir}'.")
        return []

    rows: list[dict[str, Any]] = []
    for invoice_path in invoice_files:
        print(f"Processing: {invoice_path.name}")
        try:
            fields = extract_document_fields(invoice_path, diagnostic=print)
        except Exception as error:
            # Keep one unexpected parser failure from interrupting other invoices.
            print(f"Warning: Could not process '{invoice_path.name}': {error}")
            fields = {field: "N/A" for field in FIELD_NAMES}
            fields[EXTRACTION_METHOD_COLUMN] = "Needs review"
            fields["_AI fallback attempted"] = False

        rows.append({**fields, "Source File": invoice_path.name})

    return rows


def main() -> None:
    """Run the invoice batch and save the resulting workbook."""
    rows = process_invoices()
    if not rows:
        return

    try:
        saved_path = write_excel(rows, OUTPUT_FILE)
    except Exception as error:
        print(f"Error: Could not write the Excel file '{OUTPUT_FILE}': {error}")
        raise SystemExit(1) from error

    print(f"Done. Excel file saved to: {saved_path}")


if __name__ == "__main__":
    main()
