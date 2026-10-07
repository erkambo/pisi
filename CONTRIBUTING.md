# Contributing to PISI

Thanks for wanting to help! Bug reports, ideas and code are all welcome.

## Reporting a bug or asking for something

Open an [issue](https://github.com/erkambo/pisi/issues/new/choose) and pick
the form that fits. For bugs, run PISI with `--doctor` and attach the
`doctor.txt` it writes; it holds no window titles, file names or personal
details. Security problems go through [SECURITY.md](SECURITY.md) instead,
never a public issue.

## Setting up

```bash
git clone https://github.com/erkambo/pisi.git
cd pisi
pip install -r windows/requirements-build.txt   # PyQt6, pytest, PyInstaller
make test        # the tests (headless Qt, in their own data folder)
make lint        # ruff
make run         # PISI itself
```

The extension's tests need Node: `node --test extension/test/*.mjs` (the
Python suite runs them too when Node is installed).

**Never point a script at your real data.** PISI keeps your cat in a data
folder, and a stray script can rewrite it. The tests isolate themselves. For
anything else, set `XDG_DATA_HOME`, `PISI_BRIDGE_NAME` and
`PISI_INSTANCE_NAME` to throwaway values (see
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)).

## Making a change

1. For anything bigger than a small fix, open an issue first so we can agree
   on the shape of it.
2. Branch off `main`, keep the change focused, and add or update tests.
3. `make test` and `make lint` must pass. CI runs both on Linux, Windows and
   macOS for every pull request.
4. Open a pull request and fill in the template.

## What we care about

- **Every cat.** Cats are procedural: anything that draws or moves the cat
  must work for any cat Pet Studio can make, not just the default one. The
  engine's checks (`companion/creatures/selftest.py`) and the things judge
  (`scripts/thing_judge.py`) are there for that.
- **Privacy.** Nothing leaves the computer except what a feature the person
  turned on needs. The extension sends shapes and yes/no answers, never page
  text or addresses. Changes that touch data flow need a line in the pull
  request explaining what goes where.
- **No new runtime dependencies** beyond PyQt6 and the standard library.
- **Plain, friendly words** in anything people see. Short sentences, no
  jargon, and no em dashes.
- **Code that reads like its neighbours.** Match the naming, comment style
  and idiom of the file you're in. Comments explain *why*.

## Commit messages

A short summary line in plain words ("The cat climbs table rows"), a blank
line, then what changed and why if it isn't obvious.

## Licence

By contributing you agree that your work is released under the
[MIT licence](LICENSE), like the rest of PISI.
