"""CLI integration tests."""

import os
import pytest

from ctxpack.cli.main import main

FIXTURES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestParseCommand:
    def test_parse_ctx_mod(self, capsys):
        path = os.path.join(FIXTURES_DIR, "ctx_mod.ctx")
        ret = main(["parse", path])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Magic: §CTX" in out
        assert "Layer: L2" in out

    def test_parse_json(self, capsys):
        path = os.path.join(FIXTURES_DIR, "ctx_mod.ctx")
        ret = main(["parse", path, "--json"])
        assert ret == 0
        out = capsys.readouterr().out
        assert '"magic": "§CTX"' in out or '"magic": "\\u00a7CTX"' in out
        assert '"layer": "L2"' in out
        assert '"DOMAIN"' in out

    def test_parse_spec_l2(self, capsys):
        path = os.path.join(FIXTURES_DIR, "spec", "CTXPACK-SPEC.L2.ctx")
        ret = main(["parse", path])
        assert ret == 0

    def test_parse_level1(self, capsys):
        path = os.path.join(FIXTURES_DIR, "ctx_mod.ctx")
        ret = main(["parse", path, "--level", "1"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "Sections" not in out  # Level 1 = header only

    def test_parse_nonexistent(self, capsys):
        ret = main(["parse", "nonexistent.ctx"])
        assert ret == 1


class TestValidateCommand:
    def test_validate_ctx_mod(self, capsys):
        path = os.path.join(FIXTURES_DIR, "ctx_mod.ctx")
        ret = main(["validate", path])
        # Should pass (warnings don't cause failure)
        assert ret == 0

    def test_validate_spec_l2(self, capsys):
        path = os.path.join(FIXTURES_DIR, "spec", "CTXPACK-SPEC.L2.ctx")
        ret = main(["validate", path])
        assert ret == 0


class TestFmtCommand:
    def test_fmt_ctx_mod(self, capsys):
        path = os.path.join(FIXTURES_DIR, "ctx_mod.ctx")
        ret = main(["fmt", path])
        assert ret == 0
        out = capsys.readouterr().out
        assert "§CTX" in out

    def test_fmt_ascii(self, capsys):
        path = os.path.join(FIXTURES_DIR, "ctx_mod.ctx")
        ret = main(["fmt", path, "--ascii"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "$CTX" in out
        for ch in "§±→¬★⚠≡⊥":
            assert ch not in out
