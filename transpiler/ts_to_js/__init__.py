from .eraser import erase_types
from .parser import parse
from .printer import print_js


def transpile(source: str) -> str:
    """TypeScript subset -> JavaScript: parse, erase types, print."""
    return print_js(erase_types(parse(source)))
