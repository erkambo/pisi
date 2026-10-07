"""Kinds of things. Each module has ``DEFAULT`` (a design), ``STYLES``,
``render(design, fit) -> Rendered`` and ``check(rendered, pet, fit)``."""
from . import basket, bed, bowl, post, toy

KINDS = {"bed": bed, "bowl": bowl, "post": post, "toy": toy, "basket": basket}
