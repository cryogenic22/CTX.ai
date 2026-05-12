"""Pydantic models for the py_fastapi_min fixture.

Seeds CP-008 (Pydantic BaseModel detection).
"""

from __future__ import annotations

from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str
    email: str
