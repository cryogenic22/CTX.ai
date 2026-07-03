"""Agentic benchmarks — long-running-agent context maintenance evals.

Two suites, both adapted from the standard long-context degradation
benchmarks (needle-in-a-haystack / MRCR, GraphWalks):

- trajectory_gen: synthetic coding-agent session transcripts with embedded
  needle facts and revised-value chains (proactive-interference probes).
- graph_gen: synthetic service-dependency corpora for graph-walk queries.

Run via the repo-root scripts run_agentic_niah.py / run_graphwalks_eval.py.
"""
