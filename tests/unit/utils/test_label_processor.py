"""Tests for vision-LLM label detection and cropping (utils/label_processor.py)."""

from dataclasses import dataclass
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from reserve_automation.utils.label_processor import LabelImageProcessor


@dataclass
class FakeResponse:
    content: str


def make_processor(response_content: str | None = None) -> LabelImageProcessor:
    gateway = MagicMock()
    if response_content is not None:
        gateway.complete = AsyncMock(return_value=FakeResponse(response_content))
    else:
        gateway.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    return LabelImageProcessor(gateway)


def make_image_bytes(width: int, height: int, color=(120, 30, 30)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------- parsing

class TestParseBoundingBox:
    def setup_method(self):
        self.proc = make_processor("")

    def test_qwen_fenced_json(self):
        content = '```json\n{\n    "bbox_2d": [233, 248, 763, 792]\n}\n```'
        assert self.proc._parse_bounding_box(content) == (233, 248, 763, 792)

    def test_qwen_list_with_label_key(self):
        content = '```json\n[\n    {"bbox_2d": [58, 236, 798, 924], "label": "front label"}\n]\n```'
        assert self.proc._parse_bounding_box(content) == (58, 236, 798, 924)

    def test_xywh_object(self):
        content = '{"x": 10, "y": 20, "width": 100, "height": 200}'
        assert self.proc._parse_bounding_box(content) == (10, 20, 110, 220)

    def test_minicpm_box_tag(self):
        content = "The label is at <box>120 340 880 910</box>."
        assert self.proc._parse_bounding_box(content) == (120, 340, 880, 910)

    def test_bare_array(self):
        assert self.proc._parse_bounding_box("[1, 2, 3, 4]") == (1, 2, 3, 4)

    def test_garbage_returns_none(self):
        assert self.proc._parse_bounding_box("I cannot find a label.") is None

    def test_empty_returns_none(self):
        assert self.proc._parse_bounding_box("") is None


# ------------------------------------------------------- coordinate scaling

class TestNormalizedToBounds:
    def setup_method(self):
        self.proc = make_processor("")

    def test_scales_normalized_coords_to_pixels(self):
        pad = LabelImageProcessor.PADDING_FRAC
        # 0-1000 box on a 3024x4032 image
        bounds = self.proc._normalized_to_bounds((250, 250, 750, 750), 3024, 4032)
        assert bounds is not None
        x, y, w, h = bounds
        # Center of image, half the size, plus padding on each side
        assert abs(x - (756 - pad * 1512)) <= 1
        assert abs(y - (1008 - pad * 2016)) <= 1
        assert abs(w - 1512 * (1 + 2 * pad)) <= 2
        assert abs(h - 2016 * (1 + 2 * pad)) <= 2

    def test_clamps_padding_at_image_edges(self):
        bounds = self.proc._normalized_to_bounds((0, 0, 1000, 1000), 1000, 800)
        assert bounds == (0, 0, 1000, 800)

    def test_reorders_swapped_corners(self):
        assert self.proc._normalized_to_bounds((750, 750, 250, 250), 2000, 2000) is not None

    def test_rejects_out_of_range(self):
        assert self.proc._normalized_to_bounds((0, 0, 1500, 900), 2000, 2000) is None

    def test_rejects_degenerate_box(self):
        assert self.proc._normalized_to_bounds((500, 500, 505, 505), 2000, 2000) is None

    def test_rejects_tiny_area(self):
        # 1.2% of the image area is below MIN_AREA_FRAC (2%)
        assert self.proc._normalized_to_bounds((0, 0, 110, 110), 3000, 3000) is None

    def test_rejects_wide_text_strip(self):
        # A single word of a label boxed on an already-cropped image:
        # ~3:1 wide in pixel space (observed qwen3.5 failure mode)
        assert self.proc._normalized_to_bounds((40, 60, 420, 140), 1841, 3135) is None

    def test_accepts_tall_bottle_box(self):
        # Neck-to-base etched text region on a tall photo is legitimate
        assert self.proc._normalized_to_bounds((300, 50, 700, 950), 3024, 4032) is not None


# ----------------------------------------------------------- detect + crop

class TestDetectLabelBounds:
    @pytest.mark.asyncio
    async def test_detects_and_scales(self):
        proc = make_processor('{"bbox_2d": [250, 250, 750, 750]}')
        bounds = await proc.detect_label_bounds(make_image_bytes(2000, 2000))
        assert bounds is not None
        x, y, w, h = bounds
        assert 400 < x < 500 and 400 < y < 500
        assert 1000 < w <= 1120 and 1000 < h <= 1120
        # Detection image sent to the LLM is downscaled
        call = proc.llm.complete.call_args
        det_img = Image.open(BytesIO(call.kwargs["images"][0]))
        assert max(det_img.size) <= LabelImageProcessor.DETECTION_MAX_DIM

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        proc = make_processor(None)  # gateway raises
        assert await proc.detect_label_bounds(make_image_bytes(1000, 1000)) is None

    @pytest.mark.asyncio
    async def test_unparseable_returns_none(self):
        proc = make_processor("no box here")
        assert await proc.detect_label_bounds(make_image_bytes(1000, 1000)) is None


class TestCropToLabel:
    @pytest.mark.asyncio
    async def test_crops_image_with_detected_bounds(self, tmp_path):
        proc = make_processor('{"bbox_2d": [250, 250, 750, 750]}')
        img_path = tmp_path / "label.jpg"
        img_path.write_bytes(make_image_bytes(2000, 1000))

        result = await proc.crop_to_label(img_path)

        assert result == img_path
        cropped = Image.open(img_path)
        # Roughly half the image in each dimension (plus padding)
        assert 900 < cropped.width < 1200
        assert 450 < cropped.height < 600

    @pytest.mark.asyncio
    async def test_detection_failure_keeps_original(self, tmp_path):
        proc = make_processor(None)  # gateway raises
        img_path = tmp_path / "label.jpg"
        img_path.write_bytes(make_image_bytes(800, 600))

        result = await proc.crop_to_label(img_path)

        assert result == img_path
        img = Image.open(img_path)
        assert img.size == (800, 600)  # unchanged dimensions

    @pytest.mark.asyncio
    async def test_explicit_bounds_skip_detection(self, tmp_path):
        proc = make_processor(None)  # LLM would raise if called
        img_path = tmp_path / "label.jpg"
        img_path.write_bytes(make_image_bytes(800, 600))

        result = await proc.crop_to_label(img_path, bounds=(100, 100, 300, 200))

        assert result == img_path
        assert Image.open(img_path).size == (300, 200)
        proc.llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_explicit_bounds_exceeding_image_fail(self, tmp_path):
        proc = make_processor(None)
        img_path = tmp_path / "label.jpg"
        img_path.write_bytes(make_image_bytes(400, 300))

        assert await proc.crop_to_label(img_path, bounds=(100, 100, 900, 900)) is None
