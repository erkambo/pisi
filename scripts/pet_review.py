"""Review an animation on the panel cats (dev tool, needs Pillow).

    python3 scripts/pet_review.py sheet curl                 # every frame, panel rows
    python3 scripts/pet_review.py gif curl                   # all cats animating at once
    python3 scripts/pet_review.py grid curl --frame 0        # one frame, whole panel
    python3 scripts/pet_review.py board curl:0,pickup:4,bat:5  # key frames x cats
    python3 scripts/pet_review.py sheet carry --group extremes --anchors
    python3 scripts/pet_review.py gif scratch --group owners,extremes --zoom 4

Groups: owners, extremes, samples, random (default: owners,extremes,samples).
``--anchors`` marks the rig anchors (mouth = red, paws = blue, head top =
green). ``--facing -1`` reviews the mirrored flank. Output goes to
docs/pets/local/review/ (gitignored) unless ``--out`` says otherwise.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw  # noqa: E402

from companion.creatures import api, panel  # noqa: E402

OUT = ROOT / "docs" / "pets" / "local" / "review"
BG = (206, 222, 206, 255)
FLOOR = (150, 170, 150, 255)
MARK = {"mouth": (230, 40, 40, 255), "paw": (40, 90, 230, 255), "head_top": (30, 160, 60, 255)}


def cats(groups: str):
    return panel.panel(tuple(g for g in groups.split(",") if g))


PROP = (140, 100, 60, 255)
TOY = (200, 60, 160, 255)


def props(pet: api.Creature, state: str, facing: int):
    """Stand-ins for the things a state is about (a post, a toy), so a pose
    is judged against what it's for: [(kind, (x0, y0, x1, y1))] in frame px."""
    from companion.creatures import quadmotion as QM
    a = pet.built.anat
    out = []
    if state == "scratch":
        g = QM.scratch_geometry(a)
        x = int(g["post_x"])
        out.append(("post", (x, int(g["top"]) - 6, x + 3, int(a.ground) + 2)))
    elif state in ("pickup", "drop"):
        x, y = QM.toy_spot(a)
        out.append(("toy", (x - 1, y, x + 2, y + 2)))
    elif state == "bat":
        x, _y = QM.bat_target(a)
        out.append(("toy", (x + 2, int(a.ground), x + 5, int(a.ground) + 2)))
    if facing < 0:
        w = pet.size[0]
        out = [(k, (w - 1 - x1, y0, w - 1 - x0, y1)) for k, (x0, y0, x1, y1) in out]
    return out


def cell(pet: api.Creature, state: str, i: int, facing: int, z: int, anchors: bool,
         floor: bool = True) -> Image.Image:
    w, h = pet.size
    im = Image.new("RGBA", (w, h), BG)
    pd = ImageDraw.Draw(im)
    for kind, box in props(pet, state, facing):
        pd.rectangle(box, fill=PROP if kind == "post" else TOY)
    fr = Image.frombytes("RGBA", (w, h), pet.frame(state, i, facing))
    im.alpha_composite(fr)
    im = im.resize((w * z, h * z), Image.NEAREST)
    d = ImageDraw.Draw(im)
    if floor:
        gy = (pet.built.anat.ground + 3) * z
        d.line([(0, gy), (w * z, gy)], fill=FLOOR, width=1)
    if anchors and hasattr(pet, "anchors"):
        an = pet.anchors(state, i, facing)
        pts = [("mouth", an.get("mouth"))] + [("paw", p) for p in an.get("paws", {}).values()]
        pts.append(("head_top", an.get("head_top")))
        for kind, p in pts:
            if p is None:
                continue
            x, y = p
            d.rectangle([x * z, y * z, x * z + z - 1, y * z + z - 1], outline=MARK[kind])
    return im


def sheet(args) -> Path:
    rows = cats(args.group)
    probe = api.Creature(rows[0][1])
    n = probe.states()[args.state].frames
    z = args.zoom
    cw, chh = 48 * z, 48 * z
    label_w = 150
    img = Image.new("RGBA", (label_w + cw * n, chh * len(rows) + 20), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((4, 4), f"{args.state} (facing {args.facing})", fill=(0, 0, 0, 255))
    for r, (label, g) in enumerate(rows):
        pet = api.Creature(g)
        y = 20 + r * chh
        d.text((4, y + chh // 2 - 6), label[:22], fill=(0, 0, 0, 255))
        for i in range(n):
            img.paste(cell(pet, args.state, i, args.facing, z, args.anchors), (label_w + i * cw, y))
    path = Path(args.out or OUT) / f"{args.state}_{args.group.replace(',', '+')}_sheet.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def gif(args) -> Path:
    rows = cats(args.group)
    pets = [(label, api.Creature(g)) for label, g in rows]
    spec = pets[0][1].states()[args.state]
    n, fps = spec.frames, spec.fps
    z = args.zoom
    cols = args.cols
    cw, chh = 48 * z, 48 * z + 14
    nrows = (len(pets) + cols - 1) // cols
    reps = 1 if spec.loop else 1
    frames = []
    for i in list(range(n)) * reps + ([n - 1] * int(fps) if not spec.loop else []):
        img = Image.new("RGBA", (cols * cw, nrows * chh), (255, 255, 255, 255))
        d = ImageDraw.Draw(img)
        for k, (label, pet) in enumerate(pets):
            x, y = (k % cols) * cw, (k // cols) * chh
            img.paste(cell(pet, args.state, i, args.facing, z, args.anchors), (x, y + 14))
            d.text((x + 2, y + 1), label[:20], fill=(0, 0, 0, 255))
        frames.append(img.convert("P", palette=Image.ADAPTIVE))
    path = Path(args.out or OUT) / f"{args.state}_{args.group.replace(',', '+')}.gif"
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=int(1000 / fps), loop=0, disposal=2)
    return path


def grid(args) -> Path:
    """One frame of every cat, in a grid (fast to eyeball the whole panel)."""
    rows = cats(args.group)
    z, cols = args.zoom, args.cols
    cw, chh = 48 * z, 48 * z + 14
    nrows = (len(rows) + cols - 1) // cols
    img = Image.new("RGBA", (cols * cw, nrows * chh), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    for k, (label, g) in enumerate(rows):
        pet = api.Creature(g)
        x, y = (k % cols) * cw, (k // cols) * chh
        img.paste(cell(pet, args.state, args.frame, args.facing, z, args.anchors), (x, y + 14))
        d.text((x + 2, y + 1), label[:22], fill=(0, 0, 0, 255))
    path = Path(args.out or OUT) / f"{args.state}{args.frame}_{args.group.replace(',', '+')}_grid.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def board(args) -> Path:
    """Rows = cats, columns = chosen (state, frame) pairs: every new
    animation's key frame on every cat in one picture. ``state`` is
    ``"curl:0,pickup:4,..."``."""
    picks = [(st, int(fr)) for st, fr in (x.split(":") for x in args.state.split(","))]
    rows = cats(args.group)
    z = args.zoom
    cw, chh = 48 * z, 48 * z
    label_w = 130
    img = Image.new("RGBA", (label_w + cw * len(picks), 16 + chh * len(rows)), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    for c, (st, fr) in enumerate(picks):
        d.text((label_w + c * cw + 2, 2), f"{st}:{fr}", fill=(0, 0, 0, 255))
    for r, (label, g) in enumerate(rows):
        pet = api.Creature(g)
        y = 16 + r * chh
        d.text((2, y + chh // 2 - 6), label[:20], fill=(0, 0, 0, 255))
        for c, (st, fr) in enumerate(picks):
            img.paste(cell(pet, st, fr, args.facing, z, args.anchors), (label_w + c * cw, y))
    path = Path(args.out or OUT) / f"board_{args.group.replace(',', '+')}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("sheet", "gif", "grid", "board"))
    ap.add_argument("state")
    ap.add_argument("--group", default="owners,extremes,samples")
    ap.add_argument("--zoom", type=int, default=3)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--facing", type=int, default=1)
    ap.add_argument("--anchors", action="store_true")
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    path = {"sheet": sheet, "gif": gif, "grid": grid, "board": board}[args.mode](args)
    print(path)


if __name__ == "__main__":
    main()
