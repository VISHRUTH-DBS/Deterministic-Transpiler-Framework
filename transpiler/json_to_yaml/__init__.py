from .generator import generate
from .parser import parse


def transpile(source: str) -> str:
    """JSON -> YAML (block style)."""
    return generate(parse(source))
