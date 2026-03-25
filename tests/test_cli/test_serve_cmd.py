"""Tests for ``treeloom serve`` command."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from typing import Any

import pytest

from treeloom.cli.serve_cmd import CPGHandler, run_cmd
from treeloom.export.json import from_json, to_json
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import CpgEdge, EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import CpgNode, NodeId, NodeKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loc(file: str, line: int) -> SourceLocation:
    return SourceLocation(file=Path(file), line=line)


def _build_cpg() -> CodePropertyGraph:
    """A small CPG: module -> greet function (with a param) calling helper."""
    cpg = CodePropertyGraph()

    mod = CpgNode(NodeId("mod:app:1:0:0"), NodeKind.MODULE, "app", _make_loc("app.py", 1))
    greet = CpgNode(
        NodeId("fn:app:3:0:1"), NodeKind.FUNCTION, "greet",
        _make_loc("app.py", 3), scope=mod.id,
    )
    helper = CpgNode(
        NodeId("fn:app:8:0:2"), NodeKind.FUNCTION, "helper",
        _make_loc("app.py", 8), scope=mod.id,
    )
    param = CpgNode(
        NodeId("par:app:3:10:3"), NodeKind.PARAMETER, "name",
        _make_loc("app.py", 3), scope=greet.id,
    )
    call_node = CpgNode(
        NodeId("call:app:5:4:4"), NodeKind.CALL, "helper",
        _make_loc("app.py", 5), scope=greet.id,
    )

    for node in (mod, greet, helper, param, call_node):
        cpg.add_node(node)

    cpg.add_edge(CpgEdge(mod.id, greet.id, EdgeKind.CONTAINS))
    cpg.add_edge(CpgEdge(mod.id, helper.id, EdgeKind.CONTAINS))
    cpg.add_edge(CpgEdge(greet.id, param.id, EdgeKind.HAS_PARAMETER))
    cpg.add_edge(CpgEdge(greet.id, call_node.id, EdgeKind.CONTAINS))
    cpg.add_edge(CpgEdge(call_node.id, helper.id, EdgeKind.CALLS))

    # Attach an annotation to the greet function for annotation tests.
    cpg.annotate_node(greet.id, "role", "entry_point")

    return cpg


def _free_port() -> int:
    """Return an available TCP port on localhost."""
    with socket.socket() as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


def _fetch_json(url: str) -> tuple[int, Any]:
    """Return (status_code, parsed_json) for a GET request."""
    try:
        resp = urllib.request.urlopen(url)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# ---------------------------------------------------------------------------
# Fixture: live server
# ---------------------------------------------------------------------------


@pytest.fixture()
def server(tmp_path: Path):
    """Start a CPGHandler server on a random port; yield base URL."""
    cpg = _build_cpg()
    cpg_file = tmp_path / "cpg.json"
    cpg_file.write_text(to_json(cpg))

    loaded = from_json(cpg_file.read_text())
    CPGHandler.cpg = loaded

    port = _free_port()
    srv = HTTPServer(("127.0.0.1", port), CPGHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}"

    srv.shutdown()
    srv.server_close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_returns_ok(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/health")
        assert status == 200
        assert data["status"] == "ok"

    def test_includes_counts(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/health")
        assert data["nodes"] > 0
        assert data["edges"] > 0


class TestInfoEndpoint:
    def test_returns_counts(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/info")
        assert status == 200
        assert data["node_count"] > 0
        assert data["edge_count"] > 0

    def test_nodes_by_kind(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/info")
        assert "nodes_by_kind" in data
        assert isinstance(data["nodes_by_kind"], dict)
        # Our CPG has functions
        assert "function" in data["nodes_by_kind"]

    def test_edges_by_kind(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/info")
        assert "edges_by_kind" in data
        assert "contains" in data["edges_by_kind"]

    def test_file_list(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/info")
        assert "files" in data
        assert any("app.py" in f for f in data["files"])


class TestQueryEndpoint:
    def test_no_filter_returns_all_nodes(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/query")
        assert isinstance(data, list)
        assert len(data) == 5  # mod, greet, helper, param, call_node

    def test_kind_filter(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/query?kind=function")
        assert isinstance(data, list)
        assert all(n["kind"] == "function" for n in data)
        assert {n["name"] for n in data} == {"greet", "helper"}

    def test_name_filter_regex(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/query?name=gr")
        assert any(n["name"] == "greet" for n in data)
        assert not any(n["name"] == "helper" for n in data)

    def test_file_filter(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/query?file=app.py")
        assert len(data) == 5

    def test_limit_parameter(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/query?limit=2")
        assert len(data) <= 2

    def test_invalid_kind_returns_400(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/query?kind=bogus")
        assert status == 400
        assert "error" in data

    def test_invalid_regex_returns_400(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/query?name=%5B%5Binvalid")
        assert status == 400
        assert "error" in data

    def test_node_has_annotations_field(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/query?kind=function&name=greet")
        greet = next(n for n in data if n["name"] == "greet")
        assert "annotations" in greet
        assert greet["annotations"].get("role") == "entry_point"


class TestNodeEndpoint:
    def test_lookup_by_id(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/node/fn:app:3:0:1")
        assert status == 200
        assert data["name"] == "greet"
        assert data["kind"] == "function"

    def test_includes_annotations(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/node/fn:app:3:0:1")
        assert data["annotations"]["role"] == "entry_point"

    def test_includes_attrs_and_scope(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/node/fn:app:3:0:1")
        assert "attrs" in data
        assert "scope" in data

    def test_unknown_id_returns_404(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/node/no:such:node")
        assert status == 404
        assert "error" in data


class TestEdgesEndpoint:
    def test_returns_all_edges(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/edges")
        assert isinstance(data, list)
        assert len(data) == 5

    def test_kind_filter(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/edges?kind=calls")
        assert all(e["kind"] == "calls" for e in data)
        assert len(data) == 1

    def test_source_filter(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/edges?source=fn:app:3:0:1")
        # greet CONTAINS param and call_node (2 edges)
        assert all(e["source"] == "fn:app:3:0:1" for e in data)

    def test_target_filter(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/edges?target=fn:app:8:0:2")
        assert all(e["target"] == "fn:app:8:0:2" for e in data)

    def test_invalid_kind_returns_400(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/edges?kind=bogus")
        assert status == 400
        assert "error" in data

    def test_edge_dict_shape(self, server: str) -> None:
        _, data = _fetch_json(f"{server}/edges")
        for edge in data:
            assert "source" in edge
            assert "target" in edge
            assert "kind" in edge


class TestSubgraphEndpoint:
    def test_returns_smaller_graph(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/subgraph?root=fn:app:3:0:1")
        assert status == 200
        assert "nodes" in data
        assert "edges" in data
        # Should contain greet and its direct/indirect children, not helper
        node_names = {n["name"] for n in data["nodes"]}
        assert "greet" in node_names

    def test_depth_limits_results(self, server: str) -> None:
        _, deep = _fetch_json(f"{server}/subgraph?root=mod:app:1:0:0&depth=10")
        _, shallow = _fetch_json(f"{server}/subgraph?root=mod:app:1:0:0&depth=1")
        assert len(deep["nodes"]) >= len(shallow["nodes"])

    def test_missing_root_returns_400(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/subgraph")
        assert status == 400
        assert "error" in data

    def test_unknown_root_returns_404(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/subgraph?root=no:such:node")
        assert status == 404
        assert "error" in data


class TestNotFound:
    def test_unknown_path_returns_404(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/notfound")
        assert status == 404
        assert "error" in data

    def test_root_path_returns_404(self, server: str) -> None:
        status, data = _fetch_json(f"{server}/")
        assert status == 404


# ---------------------------------------------------------------------------
# run_cmd unit tests (no live server needed)
# ---------------------------------------------------------------------------


class TestRunCmd:
    def test_missing_cpg_file_returns_1(self, tmp_path: Path, capsys) -> None:
        from argparse import Namespace

        args = Namespace(cpg_file=tmp_path / "ghost.json", host="127.0.0.1", port=9999)
        rc = run_cmd(args)
        assert rc == 1
        assert "ghost.json" in capsys.readouterr().err
