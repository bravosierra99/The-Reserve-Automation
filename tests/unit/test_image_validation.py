"""Unit tests for utils/image_validation.py — the label-image gate.

Guards against the two real prod failure modes documented in
docs/GROUND_TRUTH.md #4: manifest/invoice PDFs stored as label.jpg,
and tiny web thumbnails saved by the label-download flow.
"""

from io import BytesIO

from PIL import Image

from reserve_automation.utils.image_validation import (
    MIN_LABEL_LONG_SIDE,
    validate_label_image,
)


def _jpeg_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# Smallest syntactically-plausible PDF header + body; what a wine-record
# manifest looks like when saved under a .jpg name.
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF\n"


class TestValidateLabelImage:
    def test_accepts_normal_photo(self):
        ok, detail = validate_label_image(_jpeg_bytes(800, 1200))
        assert ok is True
        assert detail == "800x1200px"

    def test_rejects_pdf_bytes(self):
        ok, detail = validate_label_image(PDF_BYTES)
        assert ok is False
        assert "not a readable image" in detail

    def test_rejects_corrupt_bytes(self):
        ok, detail = validate_label_image(b"\xff\xd8\xff garbage not a real jpeg")
        assert ok is False
        assert "not a readable image" in detail

    def test_rejects_tiny_thumbnail(self):
        # 320px was the largest of the bad prod thumbnails
        ok, detail = validate_label_image(_jpeg_bytes(320, 240))
        assert ok is False
        assert "too small" in detail
        assert "320x240px" in detail

    def test_min_long_side_zero_skips_size_check(self):
        ok, _ = validate_label_image(_jpeg_bytes(56, 56), min_long_side=0)
        assert ok is True

    def test_boundary_exactly_min_long_side_passes(self):
        ok, _ = validate_label_image(_jpeg_bytes(MIN_LABEL_LONG_SIDE, 100))
        assert ok is True

    def test_accepts_path_input(self, tmp_path):
        p = tmp_path / "label.jpg"
        p.write_bytes(_jpeg_bytes(600, 900))
        ok, detail = validate_label_image(p)
        assert ok is True
        assert detail == "600x900px"

    def test_rejects_pdf_path_input(self, tmp_path):
        p = tmp_path / "label.jpg"
        p.write_bytes(PDF_BYTES)
        ok, detail = validate_label_image(p)
        assert ok is False
        assert "not a readable image" in detail
