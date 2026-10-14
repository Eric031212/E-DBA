"""Tiny dependency-free single-page PDF writer for the demo thesis repository."""

from __future__ import annotations

import textwrap


def _esc(s: str) -> str:
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render_pdf(title: str, lines: list[str]) -> bytes:
    ops = ["BT", "/F2 18 Tf", "72 760 Td", "22 TL"]
    for chunk in textwrap.wrap(title, 52) or [""]:
        ops.append(f"({_esc(chunk)}) Tj T*")
    ops += ["/F1 11 Tf", "15 TL", "T*"]
    for line in lines:
        for chunk in textwrap.wrap(line, 90) or [""]:
            ops.append(f"({_esc(chunk)}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
