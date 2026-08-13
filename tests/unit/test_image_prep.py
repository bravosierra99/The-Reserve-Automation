"""Tests for the shared vision-image encoder.

Regression coverage for the manifest upload timeout: the manifest path used to
send a full-resolution PNG to the vision model, which put tens of thousands of
image tokens into prefill and blew the 180s LM Studio timeout.
"""

import io

import pytest
from PIL import Image

from reserve_automation.utils.image_prep import (
    DOCUMENT_MAX_DIM,
    LABEL_MAX_DIM,
    encode_for_vision,
)


def _decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


class TestEncodeForVision:
    def test_emits_jpeg_not_png(self):
        """Vision payloads must be single-frame JPEG (MPO/PNG decoders misbehave)."""
        out = encode_for_vision(Image.new("RGB", (64, 64), "red"))
        assert _decode(out).format == "JPEG"

    def test_downscales_above_cap(self):
        """A full-res phone capture must be capped, not sent at native size."""
        out = encode_for_vision(Image.new("RGB", (4032, 3024), "white"), max_dim=1536)
        assert max(_decode(out).size) == 1536

    def test_preserves_aspect_ratio(self):
        out = encode_for_vision(Image.new("RGB", (4000, 2000), "white"), max_dim=2000)
        w, h = _decode(out).size
        assert (w, h) == (2000, 1000)

    def test_does_not_upscale_small_images(self):
        """Small documents are left alone — upscaling adds tokens, not detail."""
        out = encode_for_vision(Image.new("RGB", (320, 240), "white"), max_dim=2048)
        assert _decode(out).size == (320, 240)

    def test_converts_non_rgb(self):
        out = encode_for_vision(Image.new("RGBA", (32, 32), (1, 2, 3, 128)))
        assert _decode(out).mode == "RGB"

    def test_does_not_mutate_caller_image(self):
        """thumbnail() is in-place; the helper must not resize the caller's image."""
        src = Image.new("RGB", (4032, 3024), "white")
        encode_for_vision(src, max_dim=1536)
        assert src.size == (4032, 3024)

    def test_applies_exif_orientation(self):
        """Orientation=6 means 'rotate 90°'; a re-save drops the flag, so it
        must be baked into the pixels or the model reads the image sideways."""
        img = Image.new("RGB", (100, 50), "white")
        exif = img.getexif()
        exif[274] = 6  # Orientation
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif)

        out = encode_for_vision(Image.open(io.BytesIO(buf.getvalue())))
        assert _decode(out).size == (50, 100)

    def test_document_cap_is_looser_than_label_cap(self):
        """Manifests carry smaller glyphs than labels, so they keep more pixels."""
        assert DOCUMENT_MAX_DIM > LABEL_MAX_DIM


class TestManifestPathUsesEncoder:
    """The bug: parsers/image.py shipped a full-res PNG to the vision model."""

    @pytest.mark.asyncio
    async def test_vision_payload_is_capped_jpeg(self, tmp_path, monkeypatch):
        from reserve_automation.parsers.image import ImageParser

        # A realistic phone capture of a wine manifest.
        path = tmp_path / "manifest.jpg"
        Image.new("RGB", (4032, 3024), "white").save(path, format="JPEG")

        captured: dict = {}

        async def fake_vision(self, img_bytes):
            captured["bytes"] = img_bytes
            return "Chateau Test 2019"

        monkeypatch.setattr(ImageParser, "_ocr_vision", fake_vision)

        parser = ImageParser(ocr_method="vision", llm_gateway=object())
        result = await parser.parse(path)

        sent = _decode(captured["bytes"])
        assert sent.format == "JPEG", "full-res PNG regression"
        assert max(sent.size) <= DOCUMENT_MAX_DIM, "uncapped image regression"
        # The reported dimensions stay the true original, not the downscaled size.
        assert result.metadata["dimensions"] == (4032, 3024)
