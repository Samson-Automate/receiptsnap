"""Regression tests for rotated invoice OCR and amount consistency checks."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import extractor
from ocr_reader import _detect_skew_angle


class RotationSafetyTests(unittest.TestCase):
    def test_rotated_invoice_is_corrected_or_flagged_for_review(self) -> None:
        with TemporaryDirectory(prefix="receiptsnap_rotation_test_") as folder:
            image_path = Path(folder) / "rotated_invoice.png"
            image = Image.new("RGB", (1800, 1200), "white")
            draw = ImageDraw.Draw(image)
            font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 62)
            lines = (
                "NORTH STAR OFFICE",
                "INVOICE",
                "Invoice Number: NS-2048",
                "Invoice Date: 2020-09-19",
                "Subtotal: $100.00",
                "Tax: $20.00",
                "Grand Total: $120.00",
            )
            for index, line in enumerate(lines):
                draw.text((70, 85 + index * 118), line, fill="black", font=font)
            rotated = image.rotate(7, expand=True, fillcolor="white")
            image.close()
            rotated.save(image_path)
            rotated.close()

            with Image.open(image_path) as skewed_image:
                self.assertAlmostEqual(
                    _detect_skew_angle(skewed_image), -7.0, delta=1.0
                )
            with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
                fields = extractor.extract_document_fields(image_path)

        expected = {
            "Invoice Date": "2020-09-19",
            "Subtotal": 100.0,
            "Tax Amount": 20.0,
            "Grand Total": 120.0,
        }
        if all(fields[key] == value for key, value in expected.items()):
            self.assertEqual(fields[extractor.EXTRACTION_METHOD_COLUMN], "OCR")
        else:
            self.assertEqual(fields[extractor.EXTRACTION_METHOD_COLUMN], "Needs review")

    def test_impossible_amount_relationships_need_review(self) -> None:
        cases = (
            ("Subtotal: -10.00", "Tax: 2.00", "Grand Total: 12.00"),
            ("Subtotal: 10.00", "Tax: -2.00", "Grand Total: 12.00"),
            ("Subtotal: 10.00", "Tax: 2.00", "Grand Total: -12.00"),
            ("Subtotal: 20.00", "Tax: 2.00", "Grand Total: 18.00"),
            ("Subtotal: 10.00", "Tax: 21.00", "Grand Total: 20.00"),
        )
        for subtotal, tax, total in cases:
            with self.subTest(subtotal=subtotal, tax=tax, total=total):
                fields = extractor.parse_fields(
                    f"Test Invoice\nInvoice Date: 2020-09-19\n"
                    f"{subtotal}\n{tax}\n{total}"
                )
                self.assertEqual(
                    fields[extractor.EXTRACTION_METHOD_COLUMN], "Needs review"
                )


if __name__ == "__main__":
    unittest.main()
