from .block_parser import parse_document
from .generator import generate


def transpile(source: str) -> str:
    """Markdown subset -> HTML."""
    return generate(parse_document(source))
