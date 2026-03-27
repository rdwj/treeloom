"""Tests for language-filtered call resolution, build progress callback, and timeout."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from treeloom.graph.builder import BuildTimeoutError, CPGBuilder
from treeloom.lang.registry import LanguageRegistry
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind


# ---------------------------------------------------------------------------
# 1. Language-filtered call resolution
# ---------------------------------------------------------------------------

_PY_SRC = b"""\
def get():
    return 1

def caller():
    x = get()
"""

_JS_SRC = b"""\
function get() {
    return 2;
}

function jsCaller() {
    let x = get();
}
"""

_TS_SRC = b"""\
function tsHelper(): number {
    return get();
}
"""


class TestMultiLanguageCallResolution:
    """Call nodes are partitioned by language; function nodes are shared."""

    @pytest.fixture(autouse=True)
    def _require_grammars(self):
        pytest.importorskip("tree_sitter_python")
        pytest.importorskip("tree_sitter_javascript")

    def test_each_language_resolves_its_own_calls(self):
        """Both languages should resolve their calls (each visitor handles
        only its own CALL nodes, but can see all FUNCTION nodes)."""
        registry = LanguageRegistry.default()
        builder = CPGBuilder(registry=registry)
        builder.add_source(_PY_SRC, "app.py", "python")
        builder.add_source(_JS_SRC, "app.js", "javascript")
        cpg = builder.build()

        py_calls_resolved = 0
        js_calls_resolved = 0
        for edge in cpg.edges(kind=EdgeKind.CALLS):
            src = cpg.node(edge.source)
            if src and src.location:
                if src.location.file.suffix == ".py":
                    py_calls_resolved += 1
                elif src.location.file.suffix == ".js":
                    js_calls_resolved += 1

        assert py_calls_resolved >= 1, "Python call to get() should resolve"
        assert js_calls_resolved >= 1, "JavaScript call to get() should resolve"

    def test_call_nodes_not_duplicated_across_visitors(self):
        """Each call node should produce at most one CALLS edge — only the
        owning language's visitor resolves it."""
        registry = LanguageRegistry.default()
        builder = CPGBuilder(registry=registry)
        builder.add_source(_PY_SRC, "app.py", "python")
        builder.add_source(_JS_SRC, "app.js", "javascript")
        cpg = builder.build()

        # Count CALLS edges per source (call) node
        calls_per_source: dict[str, int] = {}
        for edge in cpg.edges(kind=EdgeKind.CALLS):
            key = str(edge.source)
            calls_per_source[key] = calls_per_source.get(key, 0) + 1

        for source_id, count in calls_per_source.items():
            assert count == 1, (
                f"Call node {source_id} has {count} CALLS edges; expected 1"
            )


class TestCrossLanguageResolution:
    """TypeScript calling a function defined in JavaScript should resolve
    because all FUNCTION nodes are shared across visitors."""

    @pytest.fixture(autouse=True)
    def _require_grammars(self):
        pytest.importorskip("tree_sitter_javascript")
        pytest.importorskip("tree_sitter_typescript")

    def test_ts_call_resolves_to_js_function(self):
        registry = LanguageRegistry.default()
        builder = CPGBuilder(registry=registry)
        builder.add_source(_JS_SRC, "lib.js", "javascript")
        builder.add_source(_TS_SRC, "app.ts", "typescript")
        cpg = builder.build()

        # Look for a CALLS edge from the .ts call to the .js function
        cross_resolved = False
        for edge in cpg.edges(kind=EdgeKind.CALLS):
            src = cpg.node(edge.source)
            tgt = cpg.node(edge.target)
            if src and tgt and src.location and tgt.location:
                if (
                    src.location.file.suffix == ".ts"
                    and tgt.location.file.suffix == ".js"
                ):
                    cross_resolved = True
                    break

        assert cross_resolved, (
            "Expected a CALLS edge from TypeScript call to JavaScript function 'get'"
        )


class TestSingleLanguageBehavior:
    """Pure-Python resolution is unchanged by the partitioning logic."""

    @pytest.fixture(autouse=True)
    def _require_grammars(self):
        pytest.importorskip("tree_sitter_python")

    def test_python_only_resolution(self):
        py_src = b"""\
def helper():
    return 42

def main():
    x = helper()
"""
        registry = LanguageRegistry.default()
        builder = CPGBuilder(registry=registry)
        builder.add_source(py_src, "app.py", "python")
        cpg = builder.build()

        calls_edges = list(cpg.edges(kind=EdgeKind.CALLS))
        assert len(calls_edges) >= 1, "helper() call should resolve"

        # Verify the resolved target is the helper function
        for edge in calls_edges:
            tgt = cpg.node(edge.target)
            if tgt and tgt.name == "helper":
                break
        else:
            pytest.fail("No CALLS edge resolving to 'helper'")


# ---------------------------------------------------------------------------
# 2. Build progress callback
# ---------------------------------------------------------------------------

class TestBuildProgressCallback:
    @pytest.fixture(autouse=True)
    def _require_grammars(self):
        pytest.importorskip("tree_sitter_python")

    def test_callback_receives_all_phases(self):
        events: list[tuple[str, str]] = []
        builder = CPGBuilder(
            registry=LanguageRegistry.default(),
            progress=lambda phase, detail: events.append((phase, detail)),
        )
        builder.add_source(b"def f(): pass\n", "t.py", "python")
        builder.build()

        phase_names = [phase for phase, _ in events]
        assert "Parse" in phase_names
        assert "CFG" in phase_names
        assert "Call resolution" in phase_names
        assert "Inter-procedural DFG" in phase_names

    def test_callback_detail_contains_timing(self):
        events: list[tuple[str, str]] = []
        builder = CPGBuilder(
            registry=LanguageRegistry.default(),
            progress=lambda phase, detail: events.append((phase, detail)),
        )
        builder.add_source(b"def f(): pass\n", "t.py", "python")
        builder.build()

        timing_pattern = re.compile(r"done \(\d+\.\d+s")
        for phase, detail in events:
            assert timing_pattern.search(detail), (
                f"Phase '{phase}' detail lacks timing info: {detail!r}"
            )


# ---------------------------------------------------------------------------
# 3. BuildTimeoutError
# ---------------------------------------------------------------------------

class TestBuildTimeoutError:
    @pytest.fixture(autouse=True)
    def _require_grammars(self):
        pytest.importorskip("tree_sitter_python")

    def test_zero_timeout_raises_after_first_phase(self):
        builder = CPGBuilder(
            registry=LanguageRegistry.default(),
            timeout=0,
        )
        builder.add_source(b"x = 1\n", "t.py", "python")

        with pytest.raises(BuildTimeoutError) as exc_info:
            builder.build()

        assert exc_info.value.phase == "Parse"
        assert exc_info.value.timeout == 0
        assert exc_info.value.elapsed >= 0

    def test_error_message_is_informative(self):
        builder = CPGBuilder(
            registry=LanguageRegistry.default(),
            timeout=0,
        )
        builder.add_source(b"x = 1\n", "t.py", "python")

        with pytest.raises(BuildTimeoutError, match="timed out"):
            builder.build()

