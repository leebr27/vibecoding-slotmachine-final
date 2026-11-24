"""Smoke test: the classroom demo replays recorded traces without a network."""
import io
from pathlib import Path

import pytest
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
HAVE_TRACES = (ROOT / "results" / "phase1" / "vibe" / "blind.jsonl").exists()


@pytest.mark.skipif(not HAVE_TRACES, reason="no recorded traces")
def test_cached_demo_script_runs():
    import sys
    sys.path.insert(0, str(ROOT / "demo"))
    from cli_demo import Demo
    buf = io.StringIO()
    demo = Demo(Console(file=buf, width=120), "cached", 0, ["r", "r", "e", "1", "2", "3", "4", "c", "q"])
    demo.run("he_fix_spaces")
    out = buf.getvalue()
    assert "SLOT MACHINE MODE" in out and "variance meter" in out
    assert "PATCH 3" in out and "q" in out
