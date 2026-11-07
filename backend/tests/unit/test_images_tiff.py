from pathlib import Path
import tracemalloc
from PIL import Image
import pytest

from app.pipeline import images as image_mod
from app.pipeline.ingest import IngestError


def _create_multiframe_tiff(path: Path, count: int, size: tuple[int, int] = (200, 200)) -> Path:
    frames = [Image.new("RGB", size, color=(i * 5 % 255, i * 10 % 255, i * 15 % 255)) for i in range(count)]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        compression="tiff_deflate",
    )
    return path


def test_multiframe_tiff_frame_count_and_single_frame(tmp_path):
    p = tmp_path / "test_5frames.tif"
    _create_multiframe_tiff(p, 5, size=(100, 100))

    count = image_mod.get_image_frame_count(p)
    assert count == 5

    frame0 = image_mod.load_single_frame(p, 0, max_pixels=10_000_000)
    assert frame0.size == (100, 100)
    assert frame0.mode == "RGB"

    frame4 = image_mod.load_single_frame(p, 4, max_pixels=10_000_000)
    assert frame4.size == (100, 100)

    with pytest.raises(IngestError) as exc_info:
        image_mod.load_single_frame(p, 5, max_pixels=10_000_000)
    assert exc_info.value.code == "PAGE_NOT_FOUND"


def test_tiff_over_limit_rejection(tmp_path, monkeypatch):
    p = tmp_path / "test_overlimit.tif"
    _create_multiframe_tiff(p, 3, size=(50, 50))

    # Temporarily lower MAX_FRAMES to 2 to test rejection without creating massive files
    monkeypatch.setattr(image_mod, "MAX_FRAMES", 2)
    with pytest.raises(IngestError) as exc_info:
        image_mod.get_image_frame_count(p)
    assert exc_info.value.code == "TOO_MANY_PAGES"


def test_tiff_memory_single_vs_all_frames(tmp_path):
    """Measure peak memory of load_frames (old path) vs load_single_frame (new path) on 50 frames."""
    p = tmp_path / "test_50frames.tif"
    _create_multiframe_tiff(p, 50, size=(400, 400))

    # Measure old path: load_frames
    tracemalloc.start()
    frames = image_mod.load_frames(p, max_pixels=50_000_000)
    _, peak_all = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(frames) == 50

    # Measure new path: load_single_frame
    tracemalloc.start()
    frame = image_mod.load_single_frame(p, 0, max_pixels=50_000_000)
    _, peak_single = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert frame is not None

    peak_all_kb = peak_all / 1024
    peak_single_kb = peak_single / 1024

    # Single frame decoding must take substantially less memory than decoding all 50 frames
    assert peak_single_kb < peak_all_kb
