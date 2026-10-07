"""Tests for orchestrator-level pure logic that doesn't need a live Companion:
the in-product setup-offer gate (offer at most once per habit)."""
from companion.store import Store
from helpers import sample_store
from companion.app import should_offer_setup, mark_setup_offered


def test_setup_offer_is_once_per_habit():
    s = sample_store()
    hid = s.habits[0]["id"]
    assert should_offer_setup(s, hid)               # first time: yes
    mark_setup_offered(s, hid)
    assert not should_offer_setup(s, hid)           # already offered: no


def test_setup_offer_persists_across_reload():
    s = sample_store()
    hid = s.habits[0]["id"]
    mark_setup_offered(s, hid)
    assert not should_offer_setup(Store(), hid)     # a fresh load remembers


def test_setup_offer_is_per_habit_independent():
    s = sample_store()
    h0, h1 = s.habits[0]["id"], s.habits[1]["id"]
    mark_setup_offered(s, h0)
    assert not should_offer_setup(s, h0)
    assert should_offer_setup(s, h1)                # a different habit is untouched


def test_mark_offered_is_idempotent():
    s = sample_store()
    hid = s.habits[0]["id"]
    mark_setup_offered(s, hid)
    mark_setup_offered(s, hid)                       # twice
    assert s.state["setup_offered"].count(hid) == 1
