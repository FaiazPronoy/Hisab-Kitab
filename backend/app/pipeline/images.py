from PIL import Image, ImageOps, ImageSequence

from app.pipeline.ingest import IngestError

MAX_FRAMES = 200


def load_frames(path, max_pixels: int) -> list[Image.Image]:
    """JPG/PNG give one frame, TIFF may give many. Each frame is one page."""
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        img = Image.open(path)
        frames = []
        for i, frame in enumerate(ImageSequence.Iterator(img)):
            if i >= MAX_FRAMES:
                break
            f = ImageOps.exif_transpose(frame.copy())
            if f.mode not in ("RGB", "L"):
                f = f.convert("RGB")
            frames.append(f)
    except Image.DecompressionBombError:
        raise IngestError("DECOMPRESSION_BOMB", "The image is too large to process safely.")
    except Exception:
        raise IngestError("CORRUPT_FILE", "The image is damaged and cannot be opened.")
    if not frames:
        raise IngestError("EMPTY_FILE", "The image has no frames.")
    return frames
