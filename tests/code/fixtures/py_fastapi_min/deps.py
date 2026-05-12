"""Dependency providers for the py_fastapi_min fixture.

Lives in its own module specifically so CP-014 (Python static call
graph) has a cross-file caller→callee edge to detect: app.py's routes
reference get_db here.
"""

from __future__ import annotations

from typing import Iterator


def get_db() -> Iterator[object]:
    """Yield a placeholder database session.

    Real apps would yield a SQLAlchemy session or similar; the fixture
    only needs *some* shape for Depends() to bind to.
    """
    yield object()
