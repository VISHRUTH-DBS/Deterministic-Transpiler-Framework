from .generator import generate
from .parser import parse


def transpile(source: str) -> str:
    """Python subset -> JavaScript."""
    return generate(parse(source))
