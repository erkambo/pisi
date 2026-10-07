"""PISI is a cat: its words, its voice, and what happens to a pet an older
build made as some other animal."""
import re
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from companion import chime, species
from companion.creatures import api
from companion.paths import sounds_dir

CREDITS = (Path(__file__).resolve().parent.parent / "assets" / "sounds" / "CREDITS.md")


@pytest.mark.parametrize("clip", [species.CAT.voice, species.CAT.happy])
def test_voices_ship_credited_and_short(clip):
    credits = CREDITS.read_text(encoding="utf-8")
    path = sounds_dir() / f"{clip}.wav"
    assert path.exists(), clip
    assert f"`{clip}.wav`" in credits, f"{clip}.wav needs a CREDITS.md row"
    with wave.open(str(path), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 22050)
        assert 0.3 <= w.getnframes() / w.getframerate() <= 4.0


def test_credits_list_every_shipped_sound_and_only_royalty_free_licences():
    rows = [r for r in CREDITS.read_text(encoding="utf-8").splitlines() if r.startswith("| `")]
    listed = {r.split("`")[1] for r in rows}
    assert listed == {p.name for p in sounds_dir().glob("*.wav")}
    for r in rows:
        lic = r.split("|")[4].strip()
        assert re.match(r"CC0|Public domain|CC BY(-SA)? \d", lic), r


def test_voice_and_happy_are_the_meow_and_the_purr():
    assert chime.resolve("voice") == "meow" and chime.resolve("happy") == "purr"
    assert chime.resolve("meow") == "meow" and chime.resolve("purr") == "purr"   # old settings
    assert chime.resolve("bowl") == "bowl"
    keys = [k for k, _ in chime.available()]
    assert keys[:2] == ["voice", "happy"]
    assert not set(keys) & species.sound_clips()       # not offered twice as raw files
    assert "Meow" in dict(chime.available())["voice"]


def test_focus_alert_plays_the_chosen_sound(monkeypatch):
    from companion import focus
    played = []
    monkeypatch.setattr(focus.chime, "play", lambda k, v=100: played.append(k))
    ctl = SimpleNamespace(store=SimpleNamespace(config={"focus_sound": "voice"}))
    ctl._cfg = lambda k, d=None: ctl.store.config.get(k, d)
    focus.FocusController._play_alert(ctl, "focus")
    assert played == ["voice"]


def test_a_pet_an_older_build_made_as_a_dog_opens_as_the_cat():
    assert species.is_cat(api.canon_genome().to_dict())
    assert not species.is_cat({"family": "dog", "genes": {}})
    assert not species.is_cat(None)
    assert api.families() == ["feline"]


def test_petting_gets_a_cat_reaction():
    from companion.brain import Brain
    from companion.store import Store
    b = Brain(Store())
    assert all(b.pet_reaction() in species.CAT.reactions for _ in range(20))
    assert b.greeting()
