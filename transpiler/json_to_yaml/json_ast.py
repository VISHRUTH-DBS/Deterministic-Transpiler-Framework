"""Typed AST for JSON. Object members are an ordered tuple of (key, value) pairs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Union


@dataclass(frozen=True)
class JsonString:
    value: str


@dataclass(frozen=True)
class JsonNumber:
    text: str  # kept as source text: no precision is lost on large ints / long decimals


@dataclass(frozen=True)
class JsonBool:
    value: bool


@dataclass(frozen=True)
class JsonNull:
    pass


@dataclass(frozen=True)
class JsonArray:
    items: Tuple["JsonValue", ...]


@dataclass(frozen=True)
class JsonObject:
    members: Tuple[Tuple[str, "JsonValue"], ...]


JsonValue = Union[JsonString, JsonNumber, JsonBool, JsonNull, JsonArray, JsonObject]
