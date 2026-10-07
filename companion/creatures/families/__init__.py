"""The built-in pet family: the cat. Importing this package registers it."""
from .base import REGISTRY, register  # noqa: F401
from . import feline

register(feline.FAMILY)
