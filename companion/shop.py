"""The treat shop: what PISI owns, what's in its corner, and buying things
with the treats earned from finished focus blocks.

Plain rules, no tricks: a fixed price list (see things/catalog.py), no
random drops, no offers that run out, treats never expire, nothing costs
real money. The starter set is always owned.
"""
from __future__ import annotations

from .things import catalog
from .things.catalog import Item

KINDS = ("bed", "toy", "post", "bowl", "basket")       # the order the shop shows them in
KIND_TITLES = {"bed": "Beds", "toy": "Toys", "post": "Scratchers", "bowl": "Bowls",
               "basket": "Toy baskets"}
OPTIONAL = ("post",)          # the corner can do without one (bed, bowl and basket stay)


def owned(store) -> list[str]:
    """Ids of everything PISI has: the starter set and whatever was bought."""
    got = [it.id for it in catalog.starter()]
    for i in store.config.get("owned") or []:
        if i in catalog.BY_ID and i not in got:
            got.append(i)
    return got


def owns(store, item_id: str) -> bool:
    return item_id in owned(store)


def placed(store) -> dict[str, str]:
    """What stands in the corner, by kind."""
    from .home import STARTER
    h = store.config.get("home")
    p = h.get("placed") if isinstance(h, dict) else None
    return dict(p) if isinstance(p, dict) else dict(STARTER)


def is_placed(store, item: Item) -> bool:
    return placed(store).get(item.kind) == item.id


def can_afford(store, item: Item) -> bool:
    return store.treats() >= item.price


def short_by(store, item: Item) -> int:
    """How many more treats (focus blocks) until it's affordable."""
    return max(0, item.price - store.treats())


def buy(store, item_id: str) -> bool:
    """Pay for it and keep it. False if it's unknown, already owned or too
    dear (nothing changes then)."""
    it = catalog.BY_ID.get(item_id)
    if it is None or owns(store, item_id) or not can_afford(store, it):
        return False
    store.add_treats(-it.price)
    store.set_config("owned", [i for i in owned(store) if i not in
                               {s.id for s in catalog.starter()}] + [item_id])
    return True


def place(store, kind: str, item_id: str | None) -> None:
    """Stand ``item_id`` in the corner (replacing that kind's thing), or
    take the kind out of the corner (``None``; only for optional kinds)."""
    h = store.config.get("home")
    h = dict(h) if isinstance(h, dict) else {}
    p = placed(store)
    if item_id is None:
        if kind in OPTIONAL:
            p.pop(kind, None)
    elif owns(store, item_id) and catalog.BY_ID[item_id].kind == kind and kind != "toy":
        p[kind] = item_id
    h["placed"] = p
    store.set_config("home", h)


def next_goal(store) -> Item | None:
    """The cheapest thing it doesn't have and can't afford yet (what the
    treats are going towards), or None."""
    want = [it for it in catalog.ITEMS if not owns(store, it.id) and not can_afford(store, it)]
    return min(want, key=lambda it: (it.price, it.id), default=None)


def just_affordable(store, before: int) -> Item | None:
    """Something that the last treat(s) made affordable (the treats went
    from ``before`` to now), cheapest first, for a little 'you can get it
    now' line. None if nothing crossed its price."""
    now = store.treats()
    crossed = [it for it in catalog.ITEMS
               if not owns(store, it.id) and before < it.price <= now]
    return min(crossed, key=lambda it: (it.price, it.id), default=None)
