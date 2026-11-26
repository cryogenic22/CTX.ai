"""CtxPack — deterministic session memory for long-running agents, plus a
zero-dependency domain-knowledge packer with progressive hydration.

"Compaction is a commit, not a loss event."
"""

__version__ = "0.5.0rc1"

__all__ = ["__version__", "brief"]


def brief(*args, **kwargs):
    """Budgeted ledger briefing. See :func:`ctxpack.agent.brief.brief`."""
    from .agent.brief import brief as _brief
    return _brief(*args, **kwargs)
