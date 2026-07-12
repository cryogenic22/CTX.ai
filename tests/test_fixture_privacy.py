"""E-6A standing gate, widened per the 2026-07-12 substantive
re-review (finding 4): NO committed fixture may carry real user data —
usernames, user-profile paths, or raw session content tied to a real
person. Fictional users authored deliberately into synthetic fixtures
are allowlisted BY NAME; any other name in a home-directory path
fails. The owner's username is forbidden outright, including the
munged Claude-project-directory form.

This sweeps ALL of tests/fixtures/**, not one fixture family — the
rank/v1-local gate remains as a tighter check on that directory.
"""

import re
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

# forbidden outright, any casing (the owner's identity)
FORBIDDEN_SUBSTRINGS = ("kapil", "c--users-kapil")

# fictional users deliberately authored into synthetic fixtures
# (gen_synth_cohort.py / gen_synth_session.py / the unicode prose
# sample). Adding a name here is a review-visible act.
ALLOWED_FICTIONAL_USERS = {"dev", "müller", "zoë"}

_HOME_SEG = re.compile(r"[\\/](?:users|home)[\\/]+([^\\/\s\"'`|>]+)",
                       re.IGNORECASE)


def test_no_committed_fixture_carries_real_user_data():
    assert FIXTURES.is_dir()
    hits = []
    for f in sorted(FIXTURES.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_bytes().decode("utf-8", errors="ignore").lower()
        rel = str(f.relative_to(FIXTURES))
        for pat in FORBIDDEN_SUBSTRINGS:
            if pat in text:
                hits.append((rel, pat))
        for m in _HOME_SEG.finditer(text):
            if m.group(1) not in ALLOWED_FICTIONAL_USERS:
                hits.append((rel, m.group(0)))
    assert not hits, (
        f"real-user data in committed fixtures (E-6A gate): {hits[:10]}")
