import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path

EXT_KIND = {
    ".pdf": "pdf", ".jpg": "image", ".jpeg": "image", ".png": "image", ".tif": "image", ".tiff": "image",
    ".xlsx": "sheet", ".xls": "sheet", ".csv": "sheet",
}
MIME = {
    ".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".tif": "image/tiff", ".tiff": "image/tiff", ".csv": "text/csv", ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# xlsx is a zip; refuse archives that would expand far beyond their size
MAX_XLSX_UNCOMPRESSED = 400 * 1024 * 1024
MAX_XLSX_RATIO = 120


class IngestError(Exception):
    """A deterministic problem with the file itself. Never retried."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class FileInfo:
    ext: str
    kind: str
    mime: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def magic_matches(ext: str, head: bytes) -> bool:
    if ext == ".pdf":
        return b"%PDF" in head[:1024]
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".tif", ".tiff"):
        return head[:4] in (b"II*\x00", b"MM\x00*")
    if ext == ".xlsx":
        return head.startswith(b"PK\x03\x04")
    if ext == ".xls":
        return head.startswith(OLE)
    if ext == ".csv":
        if b"\x00" in head[:4096] or head.startswith((b"PK", b"%PDF", OLE)):
            return False
        return True
    return False


def check_file(filename: str, path: Path) -> FileInfo:
    ext = Path(filename).suffix.lower()
    if ext == ".xlsm":
        raise IngestError("MACRO_WORKBOOK", "Macro-enabled workbooks are not accepted. Save it as .xlsx.")
    if ext not in EXT_KIND:
        raise IngestError("UNSUPPORTED_TYPE", f"Files of type '{ext or 'none'}' are not supported.")
    size = path.stat().st_size
    if size == 0:
        raise IngestError("EMPTY_FILE", "The file is empty.")
    with open(path, "rb") as f:
        head = f.read(8192)
    if not magic_matches(ext, head):
        raise IngestError("TYPE_MISMATCH", f"The file content does not match its {ext} extension.")
    if ext == ".xlsx":
        check_zip(path)
    return FileInfo(ext, EXT_KIND[ext], MIME[ext])


def check_zip(path: Path):
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            total = sum(i.file_size for i in z.infolist())
    except zipfile.BadZipFile:
        raise IngestError("CORRUPT_FILE", "The workbook is damaged and cannot be opened.")
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise IngestError("MACRO_WORKBOOK", "The workbook contains macros.")
    if total > MAX_XLSX_UNCOMPRESSED or total > MAX_XLSX_RATIO * max(path.stat().st_size, 1):
        raise IngestError("DECOMPRESSION_BOMB", "The workbook expands to an unsafe size.")


def safe_filename(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "._- " else "_" for c in Path(name).name)
    return keep.strip()[:200] or "file"
