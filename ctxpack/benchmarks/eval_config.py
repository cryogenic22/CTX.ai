"""Evaluation configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class EvalConfig:
    """Configuration for running evaluations."""

    golden_set_path: str = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "golden_set"
    )
    baselines: list[str] = field(
        default_factory=lambda: ["raw", "naive", "llm_summary", "hand"]
    )
    run_fidelity: bool = True
    run_latency: bool = False
    run_conflicts: bool = True
    run_human_eval: bool = False
    model: str = ""  # auto-detect from CTXPACK_EVAL_MODEL or provider default
    api_key_env: str = "ANTHROPIC_API_KEY"
    output_dir: str = ""

    def __post_init__(self):
        if not self.output_dir:
            self.output_dir = os.path.join(self.golden_set_path, "results")
