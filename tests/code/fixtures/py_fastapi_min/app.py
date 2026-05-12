"""Minimal FastAPI fixture for code-packer tests.

Intentionally small. Seeds CP-005 (decorator capture), CP-006 (route
detection), CP-007 (Depends extraction). Later tasks may add richer
cases under separate fixtures rather than bloating this one.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI

from tests.code.fixtures.py_fastapi_min.deps import get_db
from tests.code.fixtures.py_fastapi_min.models import User

app = FastAPI(title="py_fastapi_min")


@app.get("/users/{user_id}")
def read_user(user_id: int, db=Depends(get_db)) -> User:
    """Fetch a user by id."""
    return User(id=user_id, name="example", email="ex@example.test")


@app.post("/users")
def create_user(user: User, db=Depends(get_db)) -> User:
    """Persist a new user."""
    return user
