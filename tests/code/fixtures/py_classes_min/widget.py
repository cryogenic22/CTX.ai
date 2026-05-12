"""Fixture for CP-004 — class with methods and attributes.

Intentionally small but covers the cases CP-004 has to handle:

- regular method (`__init__`, `tick`)
- @property (`age`)
- @staticmethod (`identity`)
- @classmethod (`from_dict`)
- async method (`refresh`)
- class attribute (`MAX_TICKS`)
- typed class attribute (`name: str = ""`)
- dunder method (`__repr__`)
- property setter (`@age.setter`) — same name as the getter, must
  produce a distinct symbol entry at CP-004 (decorator distinction
  arrives at CP-005)

See EDGE_CASES.md for the test contract.
"""

from __future__ import annotations

from typing import Any


class Widget:
    MAX_TICKS = 100
    name: str = ""

    def __init__(self, name: str) -> None:
        self.name = name
        self._ticks = 0
        self._age = 0

    def tick(self) -> int:
        self._ticks += 1
        return self._ticks

    @property
    def age(self) -> int:
        return self._age

    @age.setter
    def age(self, value: int) -> None:
        self._age = value

    @staticmethod
    def identity(x: Any) -> Any:
        return x

    @classmethod
    def from_dict(cls, payload: dict) -> "Widget":
        w = cls(payload.get("name", ""))
        w._ticks = payload.get("ticks", 0)
        return w

    async def refresh(self) -> None:
        self._ticks = 0

    def __repr__(self) -> str:
        return f"Widget(name={self.name!r}, ticks={self._ticks})"
