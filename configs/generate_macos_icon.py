#!/usr/bin/env python3
"""Generate the rounded PNG and multi-size macOS ICNS application icon."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ICON_SIZES = (16, 32, 128, 256, 512)


def _rounded_png(source: Path, destination: Path) -> None:
    image = Image.open(source).convert("RGBA")
    size = min(image.size)
    left = (image.width - size) // 2
    top = (image.height - size) // 2
    image = image.crop((left, top, left + size, top + size)).resize(
        (1024, 1024),
        Image.Resampling.LANCZOS,
    )

    mask = Image.new("L", image.size, 0)
    radius = round(image.width * 0.18)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, image.width - 1, image.height - 1),
        radius=radius,
        fill=255,
    )
    image.putalpha(mask)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True)


def generate_icon(source: Path, png_output: Path, icns_output: Path) -> None:
    _rounded_png(source, png_output)
    with tempfile.TemporaryDirectory(prefix="demo-icon-") as temporary:
        iconset = Path(temporary) / "Demo.iconset"
        iconset.mkdir()
        for size in ICON_SIZES:
            for scale, suffix in ((1, ""), (2, "@2x")):
                output = iconset / f"icon_{size}x{size}{suffix}.png"
                image = Image.open(png_output)
                image.resize((size * scale, size * scale), Image.Resampling.LANCZOS).save(
                    output,
                    format="PNG",
                    optimize=True,
                )
        icns_output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["iconutil", "--convert", "icns", "--output", str(icns_output), str(iconset)],
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--png-output", type=Path, required=True)
    parser.add_argument("--icns-output", type=Path, required=True)
    args = parser.parse_args()
    generate_icon(args.source, args.png_output, args.icns_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
