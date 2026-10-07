"""Review things fitted to the panel cats (dev tool, needs Pillow).

    python3 scripts/thing_review.py inuse bed --design '{"style": "donut"}'
    python3 scripts/thing_review.py inuse bed --group extremes --state curl --frame 3
    python3 scripts/thing_review.py designs bed --cat owners        # styles x fabrics
    python3 scripts/thing_review.py gif bed --design '{"style": "box"}'

``inuse``: one cell per panel cat, the thing drawn for that cat with the cat
using it. ``designs``: many designs on one cat (the first of ``--cat``).
``--bg dark`` checks a dark wallpaper. Output: docs/pets/local/review/.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw  # noqa: E402

from companion.creatures import api, panel  # noqa: E402
from companion.things import fit as F, scene  # noqa: E402
from companion.things.kinds import KINDS  # noqa: E402

OUT = ROOT / "docs" / "pets" / "local" / "review"
BGS = {"light": (206, 222, 206, 255), "dark": (40, 44, 52, 255), "white": (240, 240, 240, 255)}


def tile(rgba, w, h, z, bg, size=(64, 52)):
    W, H = size
    im = Image.new("RGBA", (W, H), bg)
    src = Image.frombytes("RGBA", (w, h), rgba)
    im.alpha_composite(src, ((W - w) // 2, H - h - 1))
    d = ImageDraw.Draw(im)
    d.line([(0, H - 1), (W, H - 1)], fill=(120, 140, 120, 255))
    return im.resize((W * z, H * z), Image.NEAREST)


def render_for(kind, design, g):
    pet = api.Creature(g)
    th = KINDS[kind].render(design, F.measure(pet))
    return pet, th


def inuse(args, frame=None):
    rows = panel.panel(tuple(args.group.split(",")))
    design = json.loads(args.design or "{}")
    z, cols = args.zoom, args.cols
    cells = []
    for label, g in rows:
        pet, th = render_for(args.kind, design, g)
        fi = args.frame if frame is None else frame
        if args.kind == "toy":
            rgba, w, h = scene.carry(th, pet, args.state or "carrywalk", fi, args.facing)
        else:
            rgba, w, h, _ = scene.compose(th, pet, args.state, fi, args.facing)
        cells.append((label, tile(rgba, w, h, z, BGS[args.bg])))
    cw, ch = cells[0][1].size
    nrows = (len(cells) + cols - 1) // cols
    img = Image.new("RGBA", (cols * cw, nrows * (ch + 14)), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    for k, (label, im) in enumerate(cells):
        x, y = (k % cols) * cw, (k // cols) * (ch + 14)
        d.text((x + 2, y + 1), label[:24], fill=(0, 0, 0, 255))
        img.paste(im, (x, y + 14))
    return img


def designs(args):
    g = panel.panel(tuple(args.cat.split(",")))[1 if args.cat != "canon" else 0][1]
    mod = KINDS[args.kind]
    variants = [json.loads(v) for v in args.variants.split(";")] if args.variants else \
        [{"style": st, "fabric": fab, "pattern": pat}
         for st in mod.STYLES for fab, pat in (("rose", "plain"), ("sage", "stripes"),
                                                ("navy", "dots"), ("mustard", "piping"))]
    z, cols = args.zoom, args.cols
    pet = api.Creature(g)
    ft = F.measure(pet)
    cells = []
    for v in variants:
        th = mod.render(v, ft)
        if args.kind == "toy":
            rgba, w, h = scene.carry(th, pet, args.state or "carrywalk", args.frame, args.facing)
        else:
            rgba, w, h, _ = scene.compose(th, pet, args.state, args.frame, args.facing)
        cells.append((" ".join(str(x) for x in v.values()), tile(rgba, w, h, z, BGS[args.bg])))
    cw, ch = cells[0][1].size
    nrows = (len(cells) + cols - 1) // cols
    img = Image.new("RGBA", (cols * cw, nrows * (ch + 14)), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    for k, (label, im) in enumerate(cells):
        x, y = (k % cols) * cw, (k // cols) * (ch + 14)
        d.text((x + 2, y + 1), label[:30], fill=(0, 0, 0, 255))
        img.paste(im, (x, y + 14))
    return img


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("inuse", "designs", "gif"))
    ap.add_argument("kind")
    ap.add_argument("--design")
    ap.add_argument("--variants", help="';'-separated JSON designs (designs mode)")
    ap.add_argument("--group", default="owners,samples")
    ap.add_argument("--cat", default="owners")
    ap.add_argument("--state")
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--facing", type=int, default=1)
    ap.add_argument("--zoom", type=int, default=3)
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--bg", default="light", choices=tuple(BGS))
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    out = Path(args.out or OUT)
    out.mkdir(parents=True, exist_ok=True)
    tag = args.design.replace('"', "").replace(" ", "")[:40] if args.design else "default"
    if args.mode == "inuse":
        path = out / f"thing_{args.kind}_{tag}_{args.group.replace(',', '+')}.png"
        inuse(args).save(path)
    elif args.mode == "designs":
        path = out / f"thing_{args.kind}_designs.png"
        designs(args).save(path)
    else:
        g0 = panel.panel(tuple(args.group.split(",")))
        n = api.Creature(g0[0][1]).states()[args.state or "curl"].frames
        frames = [inuse(args, frame=i).convert("P", palette=Image.ADAPTIVE) for i in range(n)]
        path = out / f"thing_{args.kind}_{tag}.gif"
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=300, loop=0)
    print(path)


if __name__ == "__main__":
    main()
