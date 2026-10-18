#!/usr/bin/env python3
"""Create a tiny sample PDF for ingest demos (stdlib only)."""

from __future__ import annotations

from pathlib import Path

TEXT = """Bern Biosense Labs
Burgdorf, Canton of Bern, Switzerland

Medtech company developing implantable glucose sensors and wearable
metabolic monitoring. Seeking clinical validation, university collaboration,
and diabetes CGM research partners in the Bern region.
"""


def escape_pdf(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(text: str) -> bytes:
    # Very small single-page PDF with Helvetica text lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    y = 750
    content_lines = ["BT", "/F1 11 Tf", "14 TL", f"50 {y} Td"]
    for i, line in enumerate(lines):
        safe = escape_pdf(line)
        if i == 0:
            content_lines.append(f"({safe}) Tj")
        else:
            content_lines.append(f"T* ({safe}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    parts: list[bytes] = []
    parts.append(b"%PDF-1.4\n")
    offsets = [0]

    def add_obj(obj: bytes) -> None:
        offsets.append(sum(len(p) for p in parts))
        parts.append(obj)

    add_obj(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    add_obj(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    add_obj(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    add_obj(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("ascii")
        + stream
        + b"\nendstream\nendobj\n"
    )
    add_obj(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    xref_pos = sum(len(p) for p in parts)
    xref = [b"xref\n0 6\n", b"0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("ascii"))
    parts.extend(xref)
    parts.append(
        f"trailer<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return b"".join(parts)


def main() -> None:
    out = Path(__file__).with_name("sample_pitch.pdf")
    out.write_bytes(build_pdf(TEXT))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
