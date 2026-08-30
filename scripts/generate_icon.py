"""
Generate a placeholder reveng_icon.ico using Pillow.

Produces a multi-resolution ICO with a simple 'RE' monogram on a dark
background. Replace with a final design asset before shipping.

Usage:
    python scripts/generate_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow is required: pip install Pillow")
    sys.exit(1)

SIZES = [16, 32, 48, 256]
BG_COLOR = (30, 30, 46)       # dark background
FG_COLOR = (139, 148, 255)    # accent blue-violet
OUTPUT = Path(__file__).parent.parent / "reveng_icon.ico"


def _make_frame(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img)

    # Draw 'RE' text centered
    text = "RE"
    font_size = max(8, int(size * 0.45))
    font = None
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except (IOError, OSError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except (IOError, OSError):
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (size - w) // 2 - bbox[0]
    y = (size - h) // 2 - bbox[1]
    draw.text((x, y), text, fill=FG_COLOR, font=font)

    return img


def main() -> None:
    frames = [_make_frame(s) for s in SIZES]
    # Save as ICO with all sizes embedded
    frames[0].save(
        OUTPUT,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[1:],
    )
    print(f"Icon written to: {OUTPUT}")


if __name__ == "__main__":
    main()
