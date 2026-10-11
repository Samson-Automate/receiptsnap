"""Streamlit interface for extracting invoice and receipt data."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from excel_writer import EXCEL_COLUMNS, write_excel
from extractor import (
    EXTRACTION_METHOD_COLUMN,
    FIELD_NAMES,
    extract_document_fields,
)
from main import SUPPORTED_EXTENSIONS
from ai_extractor import is_ai_configured

APP_TITLE = "ReceiptSnap"
STATUS_COLUMN = "⚠️ Status"

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# A restrained visual system styles the native Streamlit controls and layout.
st.markdown(
    """
    <style>
      :root {
        --ink: #152c38;
        --muted: #647782;
        --accent: #087f83;
        --accent-hover: #06676b;
        --line: #e4ecef;
        --surface: #ffffff;
      }
      .block-container {max-width: 1280px; padding: 2.2rem 2.5rem 3.5rem;}
      .hero {
        position: relative;
        padding: .3rem 0 1.65rem;
        margin-bottom: 2rem;
        border-bottom: 1px solid var(--line);
      }
      .hero::after {
        content: "";
        position: absolute;
        bottom: -1px;
        left: 0;
        width: 74px;
        height: 3px;
        border-radius: 3px;
        background: var(--accent);
      }
      .brand-lockup {display: flex; align-items: center; gap: .85rem;}
      .brand-mark {
        display: grid;
        place-items: center;
        width: 42px;
        height: 42px;
        border-radius: 12px;
        color: #fff;
        background: linear-gradient(145deg, #0a9291, #086c78);
        font-size: 1.05rem;
        font-weight: 750;
        letter-spacing: -.04em;
        box-shadow: 0 5px 14px rgba(8, 127, 131, .2);
      }
      .hero h1 {font-size: 2.1rem; line-height: 1.1; letter-spacing: -.045em; font-weight: 720; color: var(--ink); margin: 0;}
      .hero p {font-size: 1rem; color: var(--muted); margin: .55rem 0 0;}
      .section-title {
        border-left: 3px solid var(--accent);
        padding-left: .7rem;
        color: var(--ink);
        font-size: 1.18rem;
        font-weight: 680;
        line-height: 1.35;
        margin: .1rem 0 1rem;
      }
      [data-testid="st-key-upload_panel"],
      [data-testid="st-key-results_panel"],
      [data-testid="st-key-download_panel"] {
        padding: 1.3rem 1.45rem;
        border: 1px solid var(--line);
        border-radius: 16px;
        background: var(--surface);
        box-shadow: 0 5px 20px rgba(24, 55, 69, .035);
      }
      [data-testid="st-key-upload_panel"] {margin-bottom: 1.65rem;}
      [data-testid="st-key-results_panel"] {margin-top: .35rem;}
      [data-testid="st-key-download_panel"] {margin-top: 1rem;}
      div[data-testid="stFileUploader"] {
        padding: .45rem;
        border: 1px dashed #b9cdd1;
        border-radius: 12px;
        background: #f8fbfc;
      }
      div[data-testid="stFileUploader"]:hover {border-color: var(--accent);}
      [data-testid="st-key-extract_button"] button,
      [data-testid="st-key-download_button"] button {
        min-height: 2.8rem;
        border: 1px solid var(--accent);
        border-radius: 10px;
        color: #fff;
        background: var(--accent);
        font-weight: 650;
        box-shadow: 0 4px 10px rgba(8, 127, 131, .14);
        transition: background-color .16s ease, border-color .16s ease,
                    box-shadow .16s ease, transform .16s ease;
      }
      [data-testid="st-key-extract_button"] button:hover,
      [data-testid="st-key-download_button"] button:hover {
        color: #fff;
        border-color: var(--accent-hover);
        background: var(--accent-hover);
        box-shadow: 0 6px 15px rgba(8, 103, 107, .22);
        transform: translateY(-1px);
      }
      [data-testid="st-key-extract_button"] button:disabled {
        color: #f2f7f7;
        border-color: #91b8ba;
        background: #91b8ba;
        box-shadow: none;
        transform: none;
      }
      [data-testid="st-key-extract_button"] button p,
      [data-testid="st-key-download_button"] button p {font-weight: 650;}
      [data-testid="stDataFrame"] {
        overflow: hidden;
        border: 1px solid var(--line);
        border-radius: 12px;
      }
      [data-testid="stDataFrame"] th {
        color: #405762;
        background: #f2f7f8;
        font-weight: 650;
      }
      section[data-testid="stSidebar"] {
        border-right: 1px solid rgba(255,255,255,.08);
        background: #102a36;
      }
      section[data-testid="stSidebar"] h2,
      section[data-testid="stSidebar"] h3 {color: #f3f8f9; letter-spacing: -.015em;}
      section[data-testid="stSidebar"] p,
      section[data-testid="stSidebar"] li {color: #d1e0e4; line-height: 1.65;}
      section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        padding: .75rem;
        border: 1px solid rgba(73, 197, 182, .25);
        border-radius: 10px;
        color: #c8e8e3;
        background: rgba(73, 197, 182, .08);
      }
      @media (max-width: 700px) {
        .block-container {padding: 1.25rem 1rem 2rem;}
        .hero h1 {font-size: 1.8rem;}
        [data-testid="st-key-upload_panel"],
        [data-testid="st-key-results_panel"],
        [data-testid="st-key-download_panel"] {padding: 1rem;}
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def _extract_upload(
    upload: Any,
    diagnostic: Any = None,
) -> tuple[dict[str, Any], str | None]:
    """Save one upload temporarily and reuse the existing PDF/image extractors."""
    try:
        with tempfile.TemporaryDirectory(prefix="receiptsnap_") as temporary_folder:
            path = Path(temporary_folder) / Path(upload.name).name
            path.write_bytes(upload.getvalue())
            fields = extract_document_fields(path, diagnostic=diagnostic)
        return {**fields, "Source File": upload.name}, None
    except Exception as error:
        return (
            {
                **{field: "N/A" for field in FIELD_NAMES},
                EXTRACTION_METHOD_COLUMN: "Needs review",
                "_AI fallback attempted": False,
                "Source File": upload.name,
            },
            str(error),
        )


def _make_excel(rows: list[dict[str, Any]]) -> bytes:
    """Create the same workbook layout as the CLI and return it for download."""
    with tempfile.TemporaryDirectory(prefix="receiptsnap_excel_") as temporary_folder:
        path = write_excel(rows, Path(temporary_folder) / "invoices.xlsx")
        return path.read_bytes()


def _failed_row(row: pd.Series) -> bool:
    """Mark rows with no values or with an unresolved critical extraction gap."""
    return (
        row.get(EXTRACTION_METHOD_COLUMN) == "Needs review"
        or all(row[field] == "N/A" for field in FIELD_NAMES)
    )


with st.sidebar:
    st.markdown("## How it works")
    st.markdown(
        "1. Upload invoices or receipt photos.\n"
        "2. ReceiptSnap extracts text locally.\n"
        "3. Review the results and download Excel."
    )
    st.divider()
    st.markdown("### Supported formats")
    st.markdown("- PDF (text or scanned)\n- JPG / JPEG\n- PNG")
    st.divider()
    st.markdown("**Simple documents:** free local OCR  \n**Complex documents:** AI assistance (Gemini)")
    if is_ai_configured():
        st.caption(
            "Privacy: documents sent for AI assistance are processed by Google's Gemini API."
        )
    else:
        st.info(
            "AI fallback not configured — add GEMINI_API_KEY for better accuracy "
            "on complex documents."
        )
    st.caption(
        "Simple OCR runs locally. If AI assistance is enabled, documents sent to "
        "Gemini are processed by Google's API."
    )

st.markdown(
    '<div class="hero"><div class="brand-lockup">'
    '<span class="brand-mark">R</span><h1>ReceiptSnap</h1></div>'
    "<p>Turn invoices &amp; receipts into Excel in seconds</p></div>",
    unsafe_allow_html=True,
)

with st.container(key="upload_panel"):
    st.markdown('<div class="section-title">Upload documents</div>', unsafe_allow_html=True)
    uploaded_files = st.file_uploader(
        "Choose invoices or receipt photos",
        type=sorted(extension.lstrip(".") for extension in SUPPORTED_EXTENSIONS),
        accept_multiple_files=True,
        help="Choose PDF, JPG, JPEG, or PNG files. Text extraction and OCR run locally.",
    )
    button_column, _ = st.columns([1, 3])
    with button_column:
        with st.container(key="extract_button"):
            extract_clicked = st.button(
                "Import and extract",
                type="primary",
                disabled=not uploaded_files,
                icon=":material/upload:",
                width="stretch",
            )

if uploaded_files:
    st.caption(f"{len(uploaded_files)} file{'s' if len(uploaded_files) != 1 else ''} selected")

if extract_clicked:
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    progress = st.progress(0, text="Preparing extraction...")
    for index, upload in enumerate(uploaded_files, start=1):
        progress.progress(
            (index - 1) / len(uploaded_files),
            text=f"Processing file {index} of {len(uploaded_files)}: {upload.name}",
        )
        row, error = _extract_upload(upload, diagnostic=st.sidebar.write)
        rows.append(row)
        if error:
            errors[upload.name] = error
        progress.progress(
            index / len(uploaded_files),
            text=f"Finished file {index} of {len(uploaded_files)}",
        )
    progress.empty()

    try:
        excel_bytes = _make_excel(rows)
    except Exception as error:
        st.error(f"Could not create the Excel workbook: {error}")
        st.stop()

    st.session_state["receiptsnap_rows"] = rows
    st.session_state["receiptsnap_excel"] = excel_bytes
    st.session_state["receiptsnap_errors"] = errors

if "receiptsnap_rows" in st.session_state:
    rows = st.session_state["receiptsnap_rows"]
    errors = st.session_state["receiptsnap_errors"]
    with st.container(key="results_panel"):
        st.markdown('<div class="section-title">Extraction results</div>', unsafe_allow_html=True)

        failed_count = sum(_failed_row(pd.Series(row)) for row in rows)
        if failed_count == len(rows):
            ai_was_attempted = any(
                row.get("_AI fallback attempted", False) for row in rows
            )
            if ai_was_attempted:
                st.warning(
                    "AI assistance was attempted but could not extract confident "
                    "data for these files — they may need manual review."
                )
            elif any(
                any(row[field] != "N/A" for field in FIELD_NAMES)
                for row in rows
            ):
                st.warning(
                    "Required fields such as invoice date or grand total could not "
                    "be extracted. AI fallback was skipped because "
                    "GEMINI_API_KEY is not set; add a key for complex documents "
                    "or review these files manually."
                )
            else:
                st.warning(
                    "No text could be extracted from these files. Try a clearer "
                    "photo with good lighting, or check that Tesseract and Poppler "
                    "are installed."
                )
        elif failed_count:
            st.info(f"{failed_count} file(s) need review; their extracted fields are marked N/A.")

        for filename, error in errors.items():
            st.warning(f"Could not fully process **{filename}**: {error}")

        result_rows = []
        for row in rows:
            is_failed = _failed_row(pd.Series(row))
            result_rows.append(
                {
                    **row,
                    STATUS_COLUMN: (
                        "⚠️ Needs review"
                        if is_failed
                        else (
                            "ℹ️ AI-assisted"
                            if row.get(EXTRACTION_METHOD_COLUMN) == "AI-assisted"
                            else "✓ Extracted"
                        )
                    ),
                }
            )
        result_columns = [*EXCEL_COLUMNS, STATUS_COLUMN]
        result_table = pd.DataFrame(result_rows, columns=result_columns)
        # Keep mixed numeric/N/A columns Arrow-compatible for Streamlit's table renderer.
        result_table = result_table.astype(str)

        def style_rows(row: pd.Series) -> list[str]:
            if row[STATUS_COLUMN] == "⚠️ Needs review":
                return ["background-color: #fff1df; color: #77410c"] * len(row)
            background = "#ffffff" if row.name % 2 == 0 else "#f7fafb"
            return [f"background-color: {background}"] * len(row)

        number_columns = ["Subtotal", "Tax Amount", "Grand Total"]
        table_style = (
            result_table.style.apply(style_rows, axis=1)
            .set_properties(subset=number_columns, **{"text-align": "right"})
            .set_properties(subset=[STATUS_COLUMN], **{"font-weight": "600"})
        )
        st.dataframe(table_style, width="stretch", hide_index=True)

    with st.container(key="download_panel"):
        st.markdown('<div class="section-title">Download your report</div>', unsafe_allow_html=True)
        with st.container(key="download_button"):
            st.download_button(
                "Download Excel",
                data=st.session_state["receiptsnap_excel"],
                file_name="invoices.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                icon=":material/download:",
                width="content",
            )
