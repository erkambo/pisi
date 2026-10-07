"""Tests for the alert-sound layer: catalogue, file lookup, volume scaling and
the (mocked) player dispatch. No real audio is ever produced."""
import struct
import wave


from companion import chime


def test_available_lists_shipped_sounds_plus_none():
    keys = [k for k, _ in chime.available()]
    assert "voice" in keys and "happy" in keys and "bowl" in keys
    assert "none" in keys                       # silent is always offered


def test_sound_path_resolves_and_rejects():
    assert chime.sound_path("meow").exists()
    assert chime.sound_path("none") is None
    assert chime.sound_path("does-not-exist") is None


def test_play_none_is_a_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(chime.subprocess, "Popen", lambda *a, **k: calls.append(a))
    chime.play("none", 70)
    chime.play("meow", 0)                        # muted
    assert calls == []


def test_play_invokes_a_player_with_the_file(monkeypatch):
    calls = []
    monkeypatch.setattr(chime.sys, "platform", "linux")
    monkeypatch.setattr(chime.shutil, "which",
                        lambda exe: "/usr/bin/paplay" if exe == "paplay" else None)
    monkeypatch.setattr(chime.subprocess, "Popen",
                        lambda cmd, **k: calls.append(cmd))
    chime.play("meow", 50)
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "paplay" and cmd[-1].endswith("meow.wav")
    assert any(a.startswith("--volume=") for a in cmd)


def test_play_swallows_player_errors(monkeypatch):
    monkeypatch.setattr(chime.sys, "platform", "linux")
    monkeypatch.setattr(chime.shutil, "which", lambda exe: "/usr/bin/paplay")
    def boom(*a, **k):
        raise OSError("nope")
    monkeypatch.setattr(chime.subprocess, "Popen", boom)
    chime.play("meow", 50)                       # must not raise


def test_scaled_copy_halves_amplitude(tmp_path):
    src = tmp_path / "tone.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(struct.pack("<4h", 10000, -10000, 20000, -20000))
    out = chime._scaled_copy(src, 50)
    with wave.open(str(out), "rb") as r:
        vals = struct.unpack("<4h", r.readframes(r.getnframes()))
    assert vals == (5000, -5000, 10000, -10000)
