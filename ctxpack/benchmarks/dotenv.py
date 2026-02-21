"""Minimal .env file loader (stdlib only, no python-dotenv dependency)."""

from __future__ import annotations

import os


def load_dotenv(path: str = "") -> None:
    """Load environment variables from a .env file.

    Searches for .env in the current directory and parent directories
    up to the repo root, unless an explicit path is provided.
    """
    if path:
        _load_file(path)
        return

    # Walk upward from CWD looking for .env
    current = os.getcwd()
    for _ in range(10):  # max depth
        env_path = os.path.join(current, ".env")
        if os.path.isfile(env_path):
            _load_file(env_path)
            return
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent


def _load_file(path: str) -> None:
    """Parse and load a .env file into os.environ."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            # Only set if not already in environment (env vars take priority)
            if key not in os.environ or not os.environ[key]:
                os.environ[key] = value
