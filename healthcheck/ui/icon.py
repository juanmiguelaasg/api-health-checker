"""Generate the app icon (.ico) in code – no image files or Pillow needed."""
from __future__ import annotations

import struct
from pathlib import Path

from . import theme as t

PULSE = [(.15, .55), (.35, .55), (.45, .28), (.58, .75), (.68, .45), (.85, .45)]


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _seg_dist(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    k = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + k * dx, ay + k * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _inside_rounded(x, y, r) -> bool:
    cx = min(max(x, r), 1 - r)
    cy = min(max(y, r), 1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size: int, ss: int = 4) -> list[tuple[int, int, int, int]]:
    bg = _rgb(t.mix(t.GREEN, t.SURFACE, 0.8))
    fg = _rgb(t.GREEN)
    half = 0.085 / 2
    pixels = []
    for py in range(size):
        for px in range(size):
            cov_bg = cov_fg = 0
            for sy in range(ss):
                for sx in range(ss):
                    x = (px + (sx + .5) / ss) / size
                    y = (py + (sy + .5) / ss) / size
                    if not _inside_rounded(x, y, 0.24):
                        continue
                    cov_bg += 1
                    if min(_seg_dist(x, y, *PULSE[i], *PULSE[i + 1]) for i in range(len(PULSE) - 1)) <= half:
                        cov_fg += 1
            n = ss * ss
            if not cov_bg:
                pixels.append((0, 0, 0, 0))
                continue
            f = cov_fg / cov_bg
            color = tuple(round(b + (c - b) * f) for b, c in zip(bg, fg))
            pixels.append((*color, round(255 * cov_bg / n)))
    return pixels


def write_ico(path: Path, sizes=(16, 24, 32, 48, 64, 128)) -> Path:
    images = []
    for s in sizes:
        px = render(s)
        rows = []
        for y in range(s - 1, -1, -1):  # BMP rows are bottom-up
            rows.append(b"".join(struct.pack("BBBB", b, g, r, a) for r, g, b, a in px[y * s:(y + 1) * s]))
        xor = b"".join(rows)
        and_row = ((s + 31) // 32) * 4
        mask = b"\x00" * and_row * s
        header = struct.pack("<IiiHHIIiiII", 40, s, s * 2, 1, 32, 0, len(xor) + len(mask), 0, 0, 0, 0)
        images.append((s, header + xor + mask))
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for s, data in images:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out += b"".join(d for _, d in images)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path


def ensure_icon() -> Path:
    path = Path(__file__).with_name("assets") / "app.ico"
    if not path.exists():
        write_ico(path)
    return path
