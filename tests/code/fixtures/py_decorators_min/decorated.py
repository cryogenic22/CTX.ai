"""Fixture for CP-005 — decorator capture."""

from __future__ import annotations


@app.get("/foo")
def simple_route():
    return {}


@app.post("/users/{uid}", tags=["users"], status_code=201)
def create_user():
    return {}


@cache
@retry(times=3, delay=0.5)
@validators.email
def heavy():
    return 1


def plain():
    return 0


class Widget:
    @staticmethod
    def static_helper():
        return 1

    @property
    def value(self) -> int:
        return 2

    @some.factory(level="info")
    @classmethod
    def classy(cls):
        return 3
