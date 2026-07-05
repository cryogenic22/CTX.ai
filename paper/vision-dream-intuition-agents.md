# Research Vision: Dream Consolidation and Intuition Agents

**Kapil Pant — March 2026**
**Status: Vision / Research Direction**

*This is independent personal research. Views are the author's own.*

---

## 1. The Observation

Human experts don't just follow rules. A senior engineer who says "this approach will fail" isn't reading a playbook. They're pattern-matching across thousands of consolidated experiences — most of which they can't articulate until pressed.

This capability has three layers in human cognition:

1. **Working memory** — what you're thinking about right now (limited, volatile)
2. **Consolidated memory** — patterns distilled from experience during sleep ("dreaming"), stored as beliefs and intuitions in long-term memory
3. **Intuition** — rapid pattern recognition against consolidated memory, experienced as "gut feeling" but actually explainable when decomposed

AI coding agents today have only Layer 1. They process the current context window — instructions, code, conversation history — and reason from there. When the session ends, everything is lost. The next session starts from scratch with the same static CLAUDE.md.

**The question: Can we give AI agents the equivalent of Layer 2 (consolidated patterns) and Layer 3 (intuition)?**

---

## 2. The Three-Layer Cognitive Architecture

### Layer 1: Mind (exists today)

What the agent processes in the current context window:

- CLAUDE.md, AGENTS.md, .claude/rules/ (static project context)
- Conversation history (session state)
- Tool results (file reads, search results, command outputs)
- Current task description

This is equivalent to human working memory. It's powerful but limited by context window size, degrades with conversation length (proactive interference, Wang & Sun 2025), and resets between sessions.

**What provides it**: Claude Code, Cursor, Codex — the agent harness.

### Layer 2: Dream (does not exist)

Between sessions, a consolidation process ("dreaming") analyzes raw experience and distills it into patterns:

**Input** (raw experience from telemetry):
- Which sections/files were accessed per session
- Which queries returned zero results
- Which guard violations were detected
- Which re-hydrations were triggered
- How session quality degraded over time
- Which changes caused test failures
- Which patterns were followed vs violated

**Process** (the "dream"):
- Aggregate across sessions (not a single session — cross-session patterns)
- Identify co-occurrence (sections A and B always accessed together)
- Identify gaps (keyword X has 40% miss rate — knowledge is missing)
- Identify drift (after tool-call 25, test-writing drops 60%)
- Identify risk (changes to module Y caused regressions 4/5 times)
- Assign confidence scores (more observations → higher confidence)
- Apply decay (patterns not reinforced by recent data lose confidence)

**Output** (consolidated patterns):
```
Pattern: co_hydration
  Sections ORDER and PAYMENT are co-accessed in 85% of sessions
  Confidence: 0.85 (47 sessions observed)
  Action: Consider bundling into a hydration group

Pattern: knowledge_gap
  Keyword "compliance audit" returns zero matches 40% of the time
  Confidence: 0.72 (15 observations)
  Action: Domain knowledge about compliance audit is incomplete

Pattern: drift_signal
  Test-writing rate drops 60% after tool-call 20 in a session
  Confidence: 0.68 (23 sessions)
  Action: Inject test-writing reminder at tool-call 15

Pattern: risk_module
  Changes to database.py caused test failures in 4/5 recent sessions
  Fan-in: 47 files depend on this module
  Confidence: 0.81 (12 observations)
  Action: Flag as high-risk, suggest writing tests FIRST

Pattern: team_tendency
  This team's PRs average 3.2 revision cycles for API endpoint changes
  But only 1.1 revision cycles for UI component changes
  Confidence: 0.75 (30 PRs observed)
  Action: API changes need more thorough pre-review context
```

These patterns are NOT rules. They're weighted observations with provenance. They update with new data. They decay without reinforcement.

**What provides it**: A `ctxpack dream` process that runs nightly/weekly over accumulated telemetry. The output is a `patterns.json` (or similar structured file) that the intuition layer reads.

### Layer 3: Intuition (does not exist)

Before an agent starts a task, the intuition layer queries consolidated patterns for relevant signals:

**Input**: Current task description + context
**Process**: Match task against pattern store
**Output**: Weighted signals with explanations

Example:

```
Task: "Add a new billing endpoint to apps/api/app/api/v1/routes/"

Intuition signals:
  ⚠ HIGH RISK (0.81): Changes to API routes in this area caused test
    failures 4/5 times in recent history. Consider writing tests FIRST.
    [Evidence: sessions #23, #31, #35, #42 — all had post-merge regressions]

  💡 PATTERN (0.85): Route changes typically need services/ context too.
    You'll likely need to hydrate both the route and its service layer.
    [Evidence: 85% co-hydration rate across 47 sessions]

  ⏰ DRIFT WARNING (0.68): Sessions working on billing code average 35
    tool calls. Test quality typically drops after tool-call 20.
    Consider committing intermediate progress.
    [Evidence: 23 sessions showed this pattern]

  📋 TEAM PATTERN (0.75): API endpoint PRs from this team average 3.2
    revision cycles. Extra upfront review context may reduce this.
    [Evidence: 30 PRs analyzed]
```

The agent doesn't follow these as rules. It weighs them alongside the current context. A 0.68 confidence signal might be overridden by strong current evidence ("this is a trivial change, the risk pattern doesn't apply"). A 0.81 confidence signal would influence the agent to take extra precautions.

**The key property: every "gut call" is explainable.** The intuition isn't magic. It's pattern recognition with citations. You can always ask "why do you feel this way?" and get a specific answer referencing specific past observations.

**What provides it**: An intuition module that reads `patterns.json`, matches against the current task, and surfaces relevant signals to the agent's context before it begins work.

---

## 3. The Dream Process — Technical Detail

### 3.1 Input: Raw Telemetry

CtxPack already produces telemetry (JSONL format) with:
```json
{
  "timestamp": "2026-03-15T10:23:45Z",
  "session_id": "abc-123",
  "question_hash": "sha256...",
  "sections_requested": ["ENTITY-ORDER", "ENTITY-PAYMENT"],
  "sections_matched": 2,
  "tokens_injected": 3847,
  "rehydration_triggered": false,
  "latency_ms": 45.2
}
```

Additional signals that should be captured:
- Guard violations (hallucinated entity names, low-confidence signals)
- Git outcomes (did the session's changes pass CI? Cause regressions?)
- Anti-slop rule hits (what conventions were violated?)
- Session duration and tool-call count
- Human feedback (PR approved? Revision requested? How many cycles?)

### 3.2 Process: Consolidation Algorithms

**Co-occurrence mining**: For each pair of sections (A, B), compute: `P(B accessed | A accessed)`. Pairs above 0.7 are "co-hydration patterns." These suggest bundling or anticipatory hydration.

**Gap detection**: For each keyword in queries, compute zero-match rate. Keywords with >30% miss rate indicate missing domain knowledge. These surface as "knowledge gaps" that should be addressed in the next pack.

**Drift curve fitting**: Plot session quality metrics (test-writing rate, guard violations, re-hydration triggers) against session length (tool-call count). Fit a degradation curve. The inflection point is the "drift threshold" — where the agent should receive a reinforcement reminder.

**Risk scoring**: For each module/file, compute: `P(test failure | this file changed)` from git history + CI data. Modules above 0.5 are "high-risk." Weight by fan-in (more dependents = higher blast radius).

**Belief updating** (Kalman-inspired): Each pattern has a confidence score. New observations update it asymptotically toward 1.0 (if confirmed) or halve it (if contradicted). Unobserved patterns decay by 0.95x per consolidation cycle. This ensures patterns reflect recent experience, not stale history.

### 3.3 Output: Pattern Store

```json
{
  "version": "1.0",
  "consolidated_at": "2026-03-20T02:00:00Z",
  "sessions_analyzed": 47,
  "time_span_days": 14,
  "patterns": [
    {
      "type": "co_hydration",
      "sections": ["ENTITY-ORDER", "ENTITY-PAYMENT"],
      "confidence": 0.85,
      "evidence_count": 47,
      "first_seen": "2026-03-06",
      "last_confirmed": "2026-03-19",
      "suggested_action": "bundle"
    },
    {
      "type": "knowledge_gap",
      "keyword": "compliance audit",
      "miss_rate": 0.40,
      "evidence_count": 15,
      "suggested_action": "add_to_corpus"
    },
    {
      "type": "drift_signal",
      "metric": "test_write_rate",
      "threshold_tool_calls": 20,
      "degradation": 0.60,
      "confidence": 0.68,
      "suggested_action": "inject_reminder_at_15"
    },
    {
      "type": "risk_module",
      "file": "apps/api/app/core/database.py",
      "failure_rate": 0.80,
      "fan_in": 47,
      "confidence": 0.81,
      "suggested_action": "test_first"
    }
  ]
}
```

### 3.4 Decay and Forgetting

Not all patterns are permanent. The Ebbinghaus forgetting curve applies:

- Patterns confirmed by recent observations strengthen (confidence → 1.0)
- Patterns not observed in 30 days decay (confidence × 0.95 per cycle)
- Patterns contradicted by new data weaken rapidly (confidence × 0.5)
- Patterns below 0.2 confidence are pruned ("forgotten")

This prevents the pattern store from accumulating stale beliefs. A pattern like "billing code is risky" might decay to zero if the team refactors billing and it stops causing failures.

---

## 4. The Intuition Agent — Technical Detail

### 4.1 Pattern Matching

Before an agent begins a task, the intuition module:

1. Extracts context signals from the task description:
   - Files mentioned → match against risk_module patterns
   - Keywords → match against knowledge_gap patterns
   - Task type (endpoint, component, fix) → match against team_tendency patterns

2. Scores pattern relevance:
   - Direct file match (task mentions database.py, pattern covers database.py) → high relevance
   - Keyword overlap (task mentions "billing", pattern covers "billing") → medium relevance
   - Category match (task is "API endpoint", pattern covers "API changes") → low relevance

3. Filters by confidence:
   - Confidence > 0.7 → surface as advisory signal
   - Confidence 0.5-0.7 → surface only if directly relevant
   - Confidence < 0.5 → do not surface (insufficient evidence)

### 4.2 Signal Presentation

Signals are injected into the agent's context as a structured advisory block — NOT as rules:

```markdown
## Intuition Signals (from 47 sessions over 14 days)

⚠ **High-risk module** (confidence: 0.81)
  database.py changes caused test failures in 4/5 recent sessions.
  47 files depend on this module. Consider writing tests FIRST.

💡 **Co-hydration pattern** (confidence: 0.85)
  When working with ORDER, you typically also need PAYMENT context.

⏰ **Drift warning** (confidence: 0.68)
  After ~20 tool calls, test-writing rate drops 60%.
  Consider committing intermediate progress.

These are observations from past sessions, not rules. Use your judgment.
```

The final line is critical: **"Use your judgment."** The intuition layer advises; the agent decides. High-confidence signals carry more weight. Low-confidence signals can be overridden.

### 4.3 Feedback Loop

After the session:
- Did the agent follow the intuition signals?
- Did the session outcome match the prediction?
- If the risk signal said "test first" and the agent did → did tests catch issues? → reinforces pattern
- If the risk signal said "test first" and the agent didn't → did regressions occur? → reinforces pattern
- If the risk signal fired but the change was clean → weakens pattern (false positive)

This creates a learning loop: intuition → action → outcome → pattern update → better intuition.

---

## 5. Analogies from Other Domains

| Human Cognition | Agent Architecture |
|---|---|
| Working memory (7±2 items) | Context window (100K-200K tokens) |
| Sleep consolidation (episodic → semantic) | `ctxpack dream` (telemetry → patterns) |
| Long-term memory (beliefs, schemas) | Pattern store (patterns.json) |
| Intuition ("gut feeling") | Intuition agent (pattern matching → signals) |
| Forgetting curve (unused memories fade) | Confidence decay (0.95x per cycle) |
| Confirmation/disconfirmation | Bayesian belief updating from outcomes |

| Recommendation Systems | Agent Architecture |
|---|---|
| User behavior logs | Telemetry JSONL |
| Collaborative filtering | Co-occurrence mining |
| Cold start problem | Minimum 2 weeks of data needed |
| Exploration vs exploitation | Confidence threshold for surfacing signals |

| Predictive Maintenance | Agent Architecture |
|---|---|
| Sensor data streams | Telemetry events |
| Degradation curves | Drift signal fitting |
| Failure prediction | Risk module scoring |
| Maintenance scheduling | "Inject reminder at tool-call 15" |

---

## 6. What CtxPack Provides Today vs What's Needed

### Already Built (the sensory system)

| Component | Status | Role in Dream/Intuition |
|---|---|---|
| Telemetry (JSONL logger) | Shipped | Raw experience capture |
| Guard (hallucination detection) | Shipped | Violation signal source |
| Re-hydration detection | Shipped | Context insufficiency signal |
| Codebase harness (anti-slop rules) | Shipped | Baseline convention awareness |
| Entity graph | Shipped | Structural relationship data |
| Keyword index | Shipped | Query pattern analysis |

### Needs Building (the cognitive layers)

| Component | Description | Depends On |
|---|---|---|
| `ctxpack dream` | Consolidation process over telemetry | 2-4 weeks of telemetry data |
| Pattern store | Structured JSON with confidence scores | Dream process |
| Intuition module | Pattern matching + signal generation | Pattern store |
| Outcome tracking | Link session actions to git/CI outcomes | Git hooks + CI integration |
| Feedback loop | Update patterns based on outcomes | Outcome tracking |

---

## 7. When to Build This

**Not now.** This vision requires telemetry data that doesn't exist yet.

### Prerequisites (in order):
1. **Ship to teams** — get pharma, analytics, and Scriptiva teams actually using CtxPack
2. **Accumulate 2-4 weeks of telemetry** — enough sessions to mine patterns
3. **Manual "dream" analysis** — look at the telemetry data yourself, see if patterns emerge
4. **If patterns are real and actionable** → build automated consolidation
5. **If patterns improve agent outcomes** → build intuition signal injection
6. **If outcomes measurably improve** → the vision is validated

Each step validates the next. Don't skip ahead.

### The First Experiment

After 2 weeks of telemetry:

```bash
# Manual dream analysis
ctxpack telemetry .ctxpack/telemetry.jsonl --json > sessions.json

# Look for:
# - Which sections are always co-accessed?
# - Which queries fail most often?
# - Do sessions degrade over time?
# - Do certain file changes correlate with regressions?
```

If you can find 3-5 actionable patterns manually, the dream process is worth automating. If the telemetry is noise, the vision needs more sensory input before consolidation adds value.

---

## 8. The Bigger Picture

This vision positions CtxPack not just as a knowledge compiler or harness generator, but as the **cognitive infrastructure for AI agent teams**:

```
Today:  Agent starts fresh every session → no learning
        Rules are static → no adaptation
        Quality depends on prompt engineering → fragile

Vision: Agent starts with consolidated patterns → learns from history
        Beliefs update from outcomes → adapts to the codebase
        Intuition signals flag risks → proactive quality
        Every "gut call" is explainable → trustworthy
```

The harness engineering community (OpenAI, Anthropic, Fowler) focuses on **constraining** agents. This vision adds **teaching** agents — not through more rules, but through consolidated experience that produces explainable intuition.

The MP3 analogy comes full circle: MP3 is a perceptual codec that understands what humans can and can't hear. The dream/intuition system is a cognitive codec that understands what agents can and can't reliably do — and adapts accordingly.

---

## References

1. Wang, C. & Sun, J.V. (2025). "Unable to Forget: Proactive Interference Reveals Working Memory Limits in LLMs Beyond Context Length." ICML 2025 Workshop.
2. Ebbinghaus, H. (1885). "Memory: A Contribution to Experimental Psychology." (Forgetting curve)
3. Walker, M.P. (2009). "The Role of Sleep in Cognition and Emotion." Annals of the New York Academy of Sciences. (Sleep consolidation)
4. Kahneman, D. (2011). "Thinking, Fast and Slow." (System 1 intuition vs System 2 reasoning)
5. Piskala, D. (2026). "From Everything-is-a-File to Files-Are-All-You-Need." arXiv:2601.11672.
6. OpenAI (2026). "Harness Engineering: Leveraging Codex in an Agent-First World."
