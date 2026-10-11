"""Local OCR helpers for receipt images and image-only PDF documents."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytesseract
import numpy as np
from pdf2image import convert_from_path
from PIL import Image, ImageOps

_WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
_MAX_DESKEW_ANGLE = 12.0


class TesseractMissingError(RuntimeError):
    """Raised when the Tesseract executable is not installed or configured."""


def _find_poppler_path() -> str | None:
    """Find Poppler from configuration, PATH, or its standard WinGet location."""
    configured_path = os.environ.get("POPPLER_PATH")
    if configured_path:
        if Path(configured_path, "pdfinfo.exe").is_file():
            return configured_path
        raise RuntimeError(
            f"POPPLER_PATH does not contain pdfinfo.exe: {configured_path}"
        )

    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        return str(Path(pdfinfo).parent)

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        for candidate in packages.glob(
            "oschwartz10612.Poppler_*/poppler-*/Library/bin"
        ):
            if (candidate / "pdfinfo.exe").is_file():
                return str(candidate)
    return None


def _configure_tesseract() -> None:
    """Find Tesseract on PATH, at the common Windows location, or via environment."""
    configured_path = os.environ.get("TESSERACT_CMD")
    if configured_path:
        executable = Path(configured_path)
        if executable.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(executable)
            return
        raise TesseractMissingError(
            f"TESSERACT_CMD points to a missing file: {configured_path}"
        )

    if shutil.which("tesseract"):
        return
    if _WINDOWS_TESSERACT.is_file():
        pytesseract.pytesseract.tesseract_cmd = str(_WINDOWS_TESSERACT)
        return

    raise TesseractMissingError(
        "Tesseract OCR was not found. Install the free UB Mannheim Windows "
        "installer from https://github.com/UB-Mannheim/tesseract/wiki, then "
        "add C:\\Program Files\\Tesseract-OCR to PATH or set TESSERACT_CMD "
        "to the full path of tesseract.exe."
    )


def _horizontal_projection_score(image: Image.Image) -> float:
    """Score how strongly dark pixels align into horizontal text rows."""
    row_counts = np.count_nonzero(np.asarray(image) < 170, axis=1)
    return float(np.var(row_counts) * len(row_counts))


def _detect_skew_angle(image: Image.Image) -> float:
    """Find a clear small text-line skew using horizontal projection alignment."""
    grayscale = ImageOps.autocontrast(ImageOps.grayscale(image))
    if grayscale.width > 900:
        height = round(grayscale.height * 900 / grayscale.width)
        grayscale = grayscale.resize((900, height), Image.Resampling.LANCZOS)

    # Ignore page edges and convert to a binary image to make line scoring stable.
    left = round(grayscale.width * 0.04)
    top = round(grayscale.height * 0.04)
    right = round(grayscale.width * 0.96)
    bottom = round(grayscale.height * 0.96)
    binary = grayscale.crop((left, top, right, bottom)).point(
        lambda pixel: 0 if pixel < 170 else 255
    )
    baseline = _horizontal_projection_score(binary)
    best_angle = 0.0
    best_score = baseline

    for step in range(-24, 25):
        angle = step * 0.5
        if angle == 0:
            continue
        candidate = binary.rotate(
            angle,
            resample=Image.Resampling.BILINEAR,
            expand=False,
            fillcolor=255,
        )
        score = _horizontal_projection_score(candidate)
        if score > best_score:
            best_angle = angle
            best_score = score

    # Require a meaningful improvement so noisy or non-document images stay untouched.
    if abs(best_angle) < 1.0 or best_score < baseline * 1.03:
        return 0.0
    return best_angle


def _deskew_image(image: Image.Image) -> Image.Image:
    """Correct a clear small rotation while leaving uncertain images unchanged."""
    angle = _detect_skew_angle(image)
    if not angle:
        return image.copy()
    return image.rotate(
        angle,
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor="white",
    )


def _preprocess_image(image: Image.Image) -> Image.Image:
    """Prepare a readable grayscale, enlarged, high-contrast image for OCR."""
    deskewed = _deskew_image(image)
    processed = ImageOps.autocontrast(ImageOps.grayscale(deskewed))
    deskewed.close()

    if processed.width < 1600:
        scale = 1600 / processed.width
        processed = processed.resize(
            (1600, round(processed.height * scale)), Image.Resampling.LANCZOS
        )

    # A simple threshold removes light background noise from scans and photos.
    return processed.point(lambda pixel: 255 if pixel > 165 else 0)


def _read_image(image: Image.Image) -> str:
    """Run local Tesseract OCR on a preprocessed image."""
    _configure_tesseract()
    return pytesseract.image_to_string(_preprocess_image(image), config="--psm 6").strip()


def extract_text_from_image(image_path: str | Path) -> str:
    """Extract text from a JPG or PNG receipt image using local Tesseract."""
    with Image.open(image_path) as image:
        return _read_image(image)


def extract_text_from_scanned_pdf(pdf_path: str | Path) -> str:
    """Convert each scanned PDF page to an image and OCR its text."""
    try:
        pages = convert_from_path(pdf_path, dpi=300, poppler_path=_find_poppler_path())
    except Exception as error:
        message = (
            "Could not convert PDF pages to images. Install Poppler and add its "
            "Library\\bin folder to PATH (or configure pdf2image's poppler_path)."
        )
        raise RuntimeError(f"{message} Details: {error}") from error

    return "\n".join(_read_image(page) for page in pages).strip()
