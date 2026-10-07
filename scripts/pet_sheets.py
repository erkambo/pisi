"""Visual verification images for the procedural pets (dev tool, needs Pillow).

    python3 scripts/pet_sheets.py all        # everything below
    python3 scripts/pet_sheets.py contact    # curated + fixed-seed random sample
    python3 scripts/pet_sheets.py states     # every state of the default cat
    python3 scripts/pet_sheets.py gifs       # walk/run/turn/transitions GIFs
    python3 scripts/pet_sheets.py readme     # the lineup GIF at the top of the README

The images go to docs/pets/img/ (the README's to docs/img/pisi.gif).
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw  # noqa: E402

from companion.creatures import api  # noqa: E402

IMG = ROOT / "docs" / "pets" / "img"
BG = (206, 222, 206, 255)
RANDOM_SEEDS = list(range(1000, 1032))      # fixed, uncurated
CURATED = [("canon", None), ("tabby", 2024), ("tuxedo", 31), ("calico", 21),
           ("siamese", 2), ("van", 404), ("ginger", 24), ("grey", 12)]


def frame_img(pet, state, i, facing=1, z=3):
    w, h = pet.size
    im = Image.frombytes("RGBA", (w, h), pet.frame(state, i, facing))
    return im.resize((w * z, h * z), Image.NEAREST)


def labelled_grid(items, cols, z=3, title=""):
    """items: (label, pet, state, frame)."""
    cell = 48 * z
    rows = (len(items) + cols - 1) // cols
    top = 22 if title else 0
    im = Image.new("RGBA", (cols * cell, top + rows * (cell + 14)), BG)
    d = ImageDraw.Draw(im)
    if title:
        d.text((6, 4), title, fill=(0, 0, 0, 255))
    for k, (lab, pet, st, i) in enumerate(items):
        x, y = (k % cols) * cell, top + (k // cols) * (cell + 14)
        im.alpha_composite(frame_img(pet, st, i, 1, z), (x, y + 14))
        d.text((x + 3, y + 1), lab, fill=(0, 0, 0, 255))
    return im


def curated_genomes():
    fam = api.family("feline")
    out = []
    for name, seed in CURATED:
        if seed is None:
            g = api.canon_genome()
        else:
            g = api.new_genome("feline", seed)
            key = {"tabby": "Ginger", "tuxedo": "Tuxedo", "calico": "Calico",
                   "siamese": "Siamese", "van": "Van kedisi", "ginger": "Ginger",
                   "grey": "Grey"}.get(name)
            if key:
                for grp, vals in fam.presets[key].items():
                    g.genes[grp].update(vals)
            if name == "tabby":
                g.genes["coat"].update(color="brown", pattern="tabby")
        g.name = name
        out.append(g)
    return out


def contact():
    IMG.mkdir(parents=True, exist_ok=True)
    cur = [(g.name, api.Creature(g)) for g in curated_genomes()]
    rnd = [(f"seed {s}", api.Creature(api.new_genome("feline", s))) for s in RANDOM_SEEDS]
    for st in ("idle", "sit", "walk", "sleep"):
        fr = 2 if st == "walk" else 0
        labelled_grid([(n, p, st, fr) for n, p in cur], 8, title=f"Curated cats - {st}"
                      ).save(IMG / f"curated_{st}.png")
        labelled_grid([(n, p, st, fr) for n, p in rnd], 8,
                      title=f"Unedited random sample, seeds {RANDOM_SEEDS[0]}-{RANDOM_SEEDS[-1]} - {st}"
                      ).save(IMG / f"random_{st}.png")
    # every family: the 6 saved samples, and an unedited random sample
    for fam in api.families():
        sm = [(g.name, api.Creature(g)) for g in api.samples(fam)]
        rows = []
        for st in ("idle", "sit", "walk", "run", "sleep"):
            fr = {"walk": 2, "run": 3}.get(st, 0)
            rows += [(f"{n} {st}", p, st, fr) for n, p in sm]
        labelled_grid(rows, 6, title=f"{fam}: saved samples (idle / sit / walk / run / sleep)"
                      ).save(IMG / f"samples_{fam}.png")
        rnd = [(f"seed {s}", api.Creature(api.new_genome(fam, s))) for s in RANDOM_SEEDS[:16]]
        labelled_grid([(n, p, "idle", 0) for n, p in rnd] + [(n, p, "walk", 2) for n, p in rnd], 8,
                      title=f"{fam}: unedited random sample, seeds {RANDOM_SEEDS[0]}-{RANDOM_SEEDS[15]} (idle, walk)"
                      ).save(IMG / f"random_{fam}.png")
    print("contact sheets ->", IMG)


def states():
    IMG.mkdir(parents=True, exist_ok=True)
    pet = api.Creature(api.canon_genome())
    z = 3
    rows = []
    for st, spec in pet.states().items():
        row = Image.new("RGBA", (110 + spec.frames * 48 * z, 48 * z), BG)
        d = ImageDraw.Draw(row)
        d.text((4, 60), f"{st}\n{spec.frames}f @{spec.fps:g}fps", fill=(0, 0, 0, 255))
        for i in range(spec.frames):
            row.alpha_composite(frame_img(pet, st, i, 1, z), (110 + i * 48 * z, 0))
        rows.append(row)
    W = max(r.width for r in rows)
    out = Image.new("RGBA", (W, sum(r.height for r in rows)), BG)
    y = 0
    for r in rows:
        out.alpha_composite(r, (0, y))
        y += r.height
    out.save(IMG / "all_states.png")
    print("states ->", IMG / "all_states.png")


def gif(pet, state, path, z=4, facing=1, travel=False, reps=3):
    spec = pet.states()[state]
    sp = pet.speed(state)
    W = 48 * z * (4 if travel else 1)
    frames = []
    for r in range(reps):
        for i in range(spec.frames):
            im = Image.new("RGBA", (W, 48 * z + 6 * z), BG)
            ImageDraw.Draw(im).rectangle([0, 48 * z, W, 48 * z + 6 * z], fill=(90, 110, 90, 255))
            k = r * spec.frames + i
            x = int(k * sp * z) % W if travel else 0
            if facing < 0 and travel:
                x = W - 48 * z - x
            im.alpha_composite(frame_img(pet, state, i, facing, z), (x, 0))
            frames.append(im.convert("P", palette=Image.ADAPTIVE))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=int(1000 / spec.fps), loop=0, disposal=2)


def gifs():
    IMG.mkdir(parents=True, exist_ok=True)
    pet = api.Creature(api.canon_genome())
    gif(pet, "walk", IMG / "walk.gif", travel=True)
    gif(pet, "run", IMG / "run.gif", travel=True)
    gif(pet, "walk", IMG / "walk_left.gif", travel=True, facing=-1)
    for st in ("turn", "sitdown", "standup", "liedown", "getup", "sit", "sleep",
               "pounce", "jump", "stretch", "dangle", "eat", "celebrate", "idle"):
        gif(pet, st, IMG / f"{st}.gif", reps=2)
    tabby = api.Creature(curated_genomes()[1])
    gif(tabby, "walk", IMG / "walk_tabby.gif", travel=True)
    for fam in ("dog", "fox", "rabbit"):
        pet = api.Creature(api.samples(fam)[0])
        for st in ("walk", "run"):
            gif(pet, st, IMG / f"{fam}_{st}.gif", travel=True)
        for st in ("turn", "sit", "meow", "sleep", "petted"):
            gif(pet, st, IMG / f"{fam}_{st}.gif", reps=2)
    print("gifs ->", IMG)


# ---- the README's lineup ---------------------------------------------------------
def _tweak(g, name, over):
    genes = copy.deepcopy(g.genes)
    for group, vals in over.items():
        genes[group].update(vals)
    return api.Genome("feline", g.seed, genes, name=name)


def lineup():
    """PISI's own tuxedo and five cats as different as Pet Studio makes them."""
    s = {g.name: g for g in api.samples("feline")}
    base = api.canon_genome()
    round_white = _tweak(base, "Round white", {
        "coat": {"color": "white", "pattern": "solid", "socks": False},
        "body": {"length": 10.0, "depth": 11.0, "legs": 6.5, "thigh": 3.6, "belly": 1.5, "chest": 3.8},
        "head": {"width": 12, "jaw": 1, "cheeks": True}, "ears": {"height": 3, "width": 4},
        "tail": {"length": 0.75, "fluff": 1.5}, "eyes": {"left": "green", "nose": "pink"}})
    lanky_silver = _tweak(base, "Lanky silver", {
        "coat": {"color": "silver", "pattern": "tabby", "socks": False},
        "body": {"length": 12.5, "depth": 7.5, "legs": 9.5, "thigh": 2.6, "chest": 2.0},
        "head": {"width": 9, "jaw": 3}, "ears": {"height": 6, "width": 4},
        "tail": {"length": 1.3, "fluff": 0.9}, "eyes": {"left": "gold", "nose": "brick"}})
    return [base, round_white, s["Ginger"], s["Calico"], s["Siamese"], lanky_silver]


# each cat walks, sits down, naps, wakes and stands, a beat after the one before
TIMELINE = (["walk"] * 16 + ["sitdown"] * 4 + ["sit"] * 10 + ["curldown"] * 6
            + ["curl"] * 10 + ["curlup"] * 5 + ["standup"] * 4)


def readme(z=3, step=6, out=ROOT / "docs" / "img" / "pisi.gif"):
    pets = [api.Creature(g) for g in lineup()]
    n = len(TIMELINE)
    frames = []
    for t in range(n):
        im = Image.new("RGBA", (len(pets) * 48 * z, 48 * z), BG)
        for k, pet in enumerate(pets):
            u = (t + k * step) % n
            st = TIMELINE[u]
            i = u - TIMELINE.index(st)                        # frame within that state
            i %= pet.states()[st].frames
            fr = Image.frombytes("RGBA", pet.size, pet.frame(st, i, 1))
            im.alpha_composite(fr.resize((48 * z, 48 * z), Image.NEAREST), (k * 48 * z, 0))
        frames.append(im)
    # trim the sky above the tallest pose, keep a little air
    top = min(f.convert("RGB").point(lambda v: 0 if v in BG[:3] else 255).getbbox()[1] for f in frames)
    top = max(0, top - 4 * z)
    frames = [f.crop((0, top, f.width, f.height)) for f in frames]
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=110, loop=0,
                   disposal=2, optimize=True)
    print(out, frames[0].size, n, "frames")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("contact", "all"):
        contact()
    if what in ("states", "all"):
        states()
    if what in ("gifs", "all"):
        gifs()
    if what in ("readme", "all"):
        readme()
