"""Broken and awkward files. Each has the outcome the system should produce."""
from pathlib import Path

import pymupdf


def build(out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    files = []

    def add(name, data, expect):
        (out / name).write_bytes(data)
        files.append({"file": name, "expect": expect})

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Invoice No: Z-1 Total 10.00")
    good = doc.tobytes()
    add("truncated.pdf", good[: len(good) // 3], "failed")
    add("renamed.pdf", b"\xff\xd8\xff\xe0" + b"0" * 2000, "rejected")
    add("empty.pdf", b"", "rejected")
    enc = pymupdf.open()
    enc.new_page().insert_text((72, 72), "secret")
    add("encrypted.pdf", enc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u"), "failed")
    add("not_a_sheet.xlsx", b"PK\x03\x04garbage", "rejected")
    add("text.exe", b"MZ", "rejected")
    return files
