"""Draw PISI's icons from its default cat (dev tool, needs Pillow).

    python3 scripts/make_icons.py

The default cat sitting, on a rounded tile, written to every place an icon
lives: the app (assets/icon.png, .ico, .icns), the browser extension
(extension/icons/) and the website (site/pisi.png). Run it again whenever the
default cat changes.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw  # noqa: E402

from companion.creatures import api  # noqa: E402

TILE = (243, 214, 160, 255)         # warm sand: black and white both read on it
SIZE = 256


def cat_frame() -> Image.Image:
    pet = api.Creature(api.canon_genome())
    im = Image.frombytes("RGBA", pet.size, pet.frame("sit", 0, 1))
    return im.crop(im.getbbox())


def icon(size: int = SIZE) -> Image.Image:
    cat = cat_frame()
    pad = round(size * 0.12)
    k = max(1, (size - 2 * pad) // max(cat.size))          # whole pixels: crisp pixel art
    cat = cat.resize((cat.width * k, cat.height * k), Image.NEAREST)
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(tile).rounded_rectangle((0, 0, size - 1, size - 1), radius=round(size * 0.18), fill=TILE)
    x = (size - cat.width) // 2
    y = size - pad - cat.height + round(size * 0.04)         # sits a little low, on the tile's floor
    tile.alpha_composite(cat, (x, y))
    return tile


def main() -> None:
    big = icon(SIZE)                                         # every size is cut from this one
    big.save(ROOT / "assets" / "icon.png")
    big.save(ROOT / "site" / "pisi.png")
    big.save(ROOT / "assets" / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                                  (64, 64), (128, 128), (256, 256)])
    big.resize((512, 512), Image.NEAREST).save(ROOT / "assets" / "icon.icns")
    for s in (16, 32, 48, 128):
        big.resize((s, s), Image.NEAREST if s == 128 else Image.LANCZOS).save(
            ROOT / "extension" / "icons" / f"icon{s}.png")
    print("icons written")


if __name__ == "__main__":
    main()
