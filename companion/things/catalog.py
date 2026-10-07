"""The catalog: a fixed, named set of things, each one through the judge.

Generators can draw endless variations; what ships is this curated list.
Every entry passed the judge on the whole review panel (see
``scripts/thing_judge.py`` and docs/things/QUALITY.md) and was looked at by
a person. Prices are in treats (one per finished focus block): toys 3-10,
furniture 10-40, special pieces 60+. ``price == 0`` is the starter set
every PISI comes with.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    kind: str
    design: dict = field(default_factory=dict, hash=False, compare=False)
    price: int = 0
    blurb: str = ""


ITEMS: tuple[Item, ...] = (
    # ---- the starter set ---------------------------------------------------------
    Item("bed.rose_donut", "Rose donut bed", "bed",
         {"style": "donut", "fabric": "rose", "lining": "blush"}, 0,
         "A soft round bolster to curl up in."),
    Item("bowl.blue", "Blue ceramic bowl", "bowl",
         {"style": "ceramic", "glaze": "glaze_blue", "contents": "food"}, 0,
         "Always a few biscuits in it."),
    Item("basket.wicker", "Wicker toy basket", "basket",
         {"style": "wicker", "toys": ("yarn_red", "yarn_blue")}, 0,
         "Where the toys live between breaks."),
    Item("toy.mouse", "Felt mouse", "toy", {"style": "mouse", "color": "felt_grey"}, 0,
         "The classic."),
    Item("toy.yarn_red", "Red yarn", "toy", {"style": "yarn", "color": "yarn_red"}, 0,
         "Unravels a little more every day."),
    # ---- toys ----------------------------------------------------------------------
    Item("toy.yarn_blue", "Blue yarn", "toy", {"style": "yarn", "color": "yarn_blue"}, 3,
         "Rolls under everything. Gets found again."),
    Item("toy.yarn_green", "Green yarn", "toy", {"style": "yarn", "color": "yarn_green"}, 3,
         "The colour of the garden it's not allowed in."),
    Item("toy.ball_gold", "Jingle ball", "toy", {"style": "ball", "color": "yarn_gold"}, 4,
         "It jingles. Constantly."),
    Item("toy.ball_blue", "Blue jingle ball", "toy", {"style": "ball", "color": "yarn_blue"}, 4,
         "Bounces off the skirting board with a ring."),
    Item("toy.crinkle", "Crinkle ball", "toy", {"style": "crinkle"}, 4,
         "Crackles when it rolls. Deeply suspicious."),
    Item("toy.fish", "Catnip fish", "toy", {"style": "fish", "color": "sky", "fin": "felt_pink"}, 5,
         "Stuffed with catnip. Gets carried everywhere."),
    Item("toy.bee", "Bumble bee", "toy", {"style": "bee"}, 6,
         "Fuzzy, stripy, and caught at last."),
    Item("toy.spring", "Rainbow spring", "toy", {"style": "spring"}, 7,
         "Boings off the floor and somewhere new."),
    # ---- bowls and baskets ---------------------------------------------------------
    Item("bowl.steel_water", "Steel water bowl", "bowl",
         {"style": "steel", "contents": "water"}, 6,
         "Fresh water, a little ripple when it drinks."),
    Item("bowl.fish", "Fish bowl", "bowl",
         {"style": "fish", "glaze": "glaze_green", "contents": "food"}, 8,
         "A little fish painted on the side."),
    Item("basket.crate", "Toy crate", "basket",
         {"style": "crate", "toys": ("yarn_gold", "yarn_green")}, 8,
         "Slatted wood. The toys peek out."),
    Item("basket.felt", "Felt toy bin", "basket",
         {"style": "felt", "toys": ("yarn_blue", "yarn_red")}, 8,
         "Soft sides, no corners to bump."),
    Item("basket.box", "Box of toys", "basket",
         {"style": "box", "toys": ("yarn_gold", "yarn_red")}, 5,
         "Flaps up, toys in. The box is also a toy."),
    Item("basket.rope", "Rope basket", "basket",
         {"style": "rope", "toys": ("yarn_green", "yarn_blue")}, 10,
         "Coiled cotton rope, soft at the edges."),
    Item("basket.chest", "Toy chest", "basket",
         {"style": "chest", "wood": "walnut", "lining": "cherry", "toys": ("yarn_blue", "yarn_gold")},
         22, "Lid up, red velvet inside. Treasure."),
    Item("bowl.stoneware", "Stoneware bowl", "bowl",
         {"style": "speckled", "glaze": "oatmeal", "contents": "food"}, 7,
         "Speckled, heavy, never tips over."),
    Item("bowl.stand", "Bowl on a stand", "bowl",
         {"style": "stand", "wood": "oak", "contents": "food"}, 12,
         "Dinner, served at a civilised height."),
    Item("bowl.fountain", "Water fountain", "bowl",
         {"style": "fountain", "glaze": "mint", "contents": "water"}, 18,
         "Running water. Much better than still."),
    # ---- beds ----------------------------------------------------------------------
    Item("bed.box", "Cardboard box", "bed", {"style": "box"}, 10,
         "If it fits, it sits."),
    Item("bed.navy_pillow", "Navy dot pillow", "bed",
         {"style": "pillow", "fabric": "navy", "pattern": "dots"}, 15,
         "Flat, squashy, perfect for a sprawl."),
    Item("bed.sky_pillow", "Cloud pillow", "bed",
         {"style": "pillow", "fabric": "sky", "pattern": "plain"}, 15,
         "Sky blue and very nearly as soft."),
    Item("bed.mint_cup", "Mint piped bed", "bed",
         {"style": "cup", "fabric": "mint", "lining": "oatmeal", "pattern": "piping",
          "trim": "porcelain"}, 22,
         "Fresh mint with white piping."),
    Item("bed.sage_cup", "Sage striped bed", "bed",
         {"style": "cup", "fabric": "sage", "lining": "oatmeal", "pattern": "stripes"}, 20,
         "High sides for a proper hide-away."),
    Item("bed.lavender_cup", "Lavender bed", "bed",
         {"style": "cup", "fabric": "lavender", "lining": "blush"}, 20,
         "Deep and cosy, with a blush lining."),
    Item("bed.wicker", "Wicker bed", "bed", {"style": "basket", "lining": "rose"}, 25,
         "A woven basket with a cushion inside."),
    Item("bed.mustard_donut", "Mustard piped donut", "bed",
         {"style": "donut", "fabric": "mustard", "lining": "oatmeal", "pattern": "piping",
          "trim": "porcelain"}, 30,
         "The fancy one. Piped edges, sunny yellow."),
    Item("bed.cave", "Hooded cave", "bed",
         {"style": "cave", "fabric": "terracotta", "lining": "oatmeal"}, 35,
         "A roof overhead. Nobody can see in. Probably."),
    Item("bed.teacup", "Teacup", "bed",
         {"style": "teacup", "lining": "blush", "trim": "glaze_blue"}, 40,
         "A cup of cat, on a saucer."),
    Item("bed.sofa", "Little sofa", "bed",
         {"style": "sofa", "fabric": "cherry", "legs": "walnut"}, 45,
         "Buttoned, with arms. Strictly for naps."),
    # ---- scratchers ----------------------------------------------------------------
    Item("post.cardboard", "Cardboard scratcher", "post", {"style": "cardboard", "base": "oak"}, 15,
         "Corrugated, shreddable, cheerfully cheap."),
    Item("post.sisal", "Sisal post", "post", {"style": "sisal", "base": "oak"}, 25,
         "Saves the sofa."),
    Item("post.log", "Log scratcher", "post", {"style": "log", "base": "walnut"}, 35,
         "A real-looking log. Very satisfying bark."),
    Item("post.tower", "Cat tower", "post", {"style": "tower", "base": "oak", "top": "rose"}, 60,
         "A platform at the top and a pom-pom to bat at."),
    Item("post.cactus", "Cactus scratcher", "post", {"style": "cactus"}, 40,
         "Sisal where it counts. It flowers, too."),
    Item("post.deluxe", "Deluxe tower", "post",
         {"style": "deluxe", "base": "birch", "top": "lavender"}, 90,
         "Two levels, a cushion on top. The big one."),
)

BY_ID = {it.id: it for it in ITEMS}


def starter() -> list[Item]:
    return [it for it in ITEMS if it.price == 0]


def of_kind(kind: str) -> list[Item]:
    return [it for it in ITEMS if it.kind == kind]
