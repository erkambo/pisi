"""(Re)generate the saved sample genomes: 6 per family, each a family preset
on a *different* rolled anatomy (so the samples differ in build, not just
colour). Output: companion/creatures/samples/<family>/<name>.pisipet.json

    python3 scripts/pet_samples.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion.creatures import api  # noqa: E402

OUT = ROOT / "companion" / "creatures" / "samples"
SEEDS = {"feline": [11, 23, 37, 41, 59, 73]}


def main():
    for fam_name in api.families():
        fam = api.family(fam_name)
        d = OUT / fam_name
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.pisipet.json"):
            old.unlink()
        names = list(fam.presets)[:6]
        if fam_name == "feline":
            names = ["Black", "Tuxedo", "Calico", "Siamese", "Ginger", "Van kedisi"]
        for k, (name, seed) in enumerate(zip(names, SEEDS[fam_name])):
            base = api.canon_genome(fam_name)
            g = api.new_genome(fam_name, seed, base=base, locked={"coat", "eyes"})
            for grp, vals in fam.presets[name].items():
                g.genes[grp].update(vals)
            if fam_name == "feline" and name == "Black":
                g = api.classic_genome()                # the black cat from before 1.0
                g.seed = seed
            g.name = name
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            (d / f"{k + 1:02d}-{slug}.pisipet.json").write_text(g.to_json() + "\n", "utf-8")
        print(fam_name, "->", d)


if __name__ == "__main__":
    main()
