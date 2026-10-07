"""Re-record the procedural pet golden pixel hashes.

Run only when the look is *meant* to change (and bump
companion/creatures/genome.py GENERATOR so saved caches are rebuilt):

    python3 scripts/pet_golden.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from companion.creatures import selftest  # noqa: E402

path = Path(selftest.__file__)
src = path.read_text("utf-8")
new = json.dumps(selftest.golden_now(), indent=4, sort_keys=True)
src = re.sub(r"GOLDEN: dict\[str, str\] = \{.*?\n\}|GOLDEN: dict\[str, str\] = \{\}",
             "GOLDEN: dict[str, str] = " + new, src, count=1, flags=re.S)
path.write_text(src, "utf-8")
print(f"recorded {len(selftest.GOLDEN_CASES)} golden hashes in {path}")
