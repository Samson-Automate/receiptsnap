# ReceiptSnap — Invoice & Receipt to Excel Extractor

✅ 27/27 QA tests passed

ReceiptSnap extracts invoice and receipt fields from PDF and image files, using local OCR first.
It exports the results to a formatted Excel workbook, with optional Gemini assistance for complex documents.

## Features

- Hybrid local OCR with an optional Gemini AI fallback
- Automatic image deskewing before OCR
- Amount consistency checks with **Needs review** flags
- Batch processing for PDF, JPG, JPEG, and PNG files
- US and European number formats
- Formatted Excel export with extraction method tracking

## Tech stack

Python, Tesseract OCR, Google Gemini, Streamlit, Pillow (PIL), pdfplumber, pandas, and openpyxl.

## Quick start

```powershell
python -m venv .venv
pip install -r requirements.txt
streamlit run app.py
```

Set the `GEMINI_API_KEY` environment variable to enable AI fallback. This is optional; the app works without it using local OCR.

## Screenshots

_Screenshot placeholder — add ReceiptSnap UI screenshots here._
