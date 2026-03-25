"""``treeloom serve`` -- serve a CPG over a local HTTP JSON API."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from treeloom.cli._util import load_cpg
from treeloom.cli.config import Config
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeId, NodeKind


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser(
        "serve",
        help="Serve a CPG as a local HTTP JSON API",
    )
    p.add_argument("cpg_file", type=Path, help="CPG JSON file to serve")
    p.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8080, help="Port number (default: 8080)")
    p.set_defaults(func=run_cmd)


class CPGHandler(BaseHTTPRequestHandler):
    """HTTP request handler backed by a loaded CodePropertyGraph."""

    # Set as a class variable before creating the server.
    cpg: Any = None  # CodePropertyGraph

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        try:
            if path == "/health":
                self._json_response({
                    "status": "ok",
                    "nodes": self.cpg.node_count,
                    "edges": self.cpg.edge_count,
                })
            elif path == "/info":
                self._handle_info()
            elif path == "/query":
                self._handle_query(params)
            elif path.startswith("/node/"):
                node_id_str = path[len("/node/"):]
                self._handle_node(node_id_str)
            elif path == "/edges":
                self._handle_edges(params)
            elif path == "/subgraph":
                self._handle_subgraph(params)
            else:
                self._json_error(404, f"Unknown path: {path}")
        except Exception as exc:  # noqa: BLE001
            self._json_error(500, str(exc))

    def _handle_info(self) -> None:
        node_counts: Counter[str] = Counter()
        for node in self.cpg.nodes():
            node_counts[node.kind.value] += 1

        edge_counts: Counter[str] = Counter()
        for edge in self.cpg.edges():
            edge_counts[edge.kind.value] += 1

        self._json_response({
            "node_count": self.cpg.node_count,
            "edge_count": self.cpg.edge_count,
            "file_count": len(self.cpg.files),
            "files": [str(f) for f in self.cpg.files],
            "nodes_by_kind": dict(node_counts.most_common()),
            "edges_by_kind": dict(edge_counts.most_common()),
        })

    def _handle_query(self, params: dict[str, list[str]]) -> None:
        kind_filter: NodeKind | None = None
        raw_kind = _first(params, "kind")
        if raw_kind is not None:
            try:
                kind_filter = NodeKind(raw_kind)
            except ValueError:
                self._json_error(400, f"Unknown node kind: {raw_kind!r}")
                return

        name_pattern = _first(params, "name")
        name_re: re.Pattern[str] | None = None
        if name_pattern is not None:
            try:
                name_re = re.compile(name_pattern)
            except re.error as exc:
                self._json_error(400, f"Invalid name regex: {exc}")
                return

        file_substr = _first(params, "file")
        limit = _int_param(params, "limit", default=50)

        results = []
        for node in self.cpg.nodes(kind=kind_filter):
            if name_re is not None and not name_re.search(node.name):
                continue
            if file_substr is not None:
                loc_file = str(node.location.file) if node.location else ""
                if file_substr not in loc_file:
                    continue
            results.append(_node_to_dict(node, self.cpg))
            if len(results) >= limit:
                break

        self._json_response(results)

    def _handle_node(self, node_id_str: str) -> None:
        if not node_id_str:
            self._json_error(400, "Node ID is required")
            return

        node = self.cpg.node(NodeId(node_id_str))
        if node is None:
            self._json_error(404, f"Node not found: {node_id_str!r}")
            return

        self._json_response(_node_to_dict(node, self.cpg))

    def _handle_edges(self, params: dict[str, list[str]]) -> None:
        kind_filter: EdgeKind | None = None
        raw_kind = _first(params, "kind")
        if raw_kind is not None:
            try:
                kind_filter = EdgeKind(raw_kind)
            except ValueError:
                self._json_error(400, f"Unknown edge kind: {raw_kind!r}")
                return

        source_filter = _first(params, "source")
        target_filter = _first(params, "target")
        limit = _int_param(params, "limit", default=200)

        results = []
        for edge in self.cpg.edges(kind=kind_filter):
            if source_filter is not None and str(edge.source) != source_filter:
                continue
            if target_filter is not None and str(edge.target) != target_filter:
                continue
            results.append({
                "source": str(edge.source),
                "target": str(edge.target),
                "kind": edge.kind.value,
                "attrs": edge.attrs,
            })
            if len(results) >= limit:
                break

        self._json_response(results)

    def _handle_subgraph(self, params: dict[str, list[str]]) -> None:
        root_str = _first(params, "root")
        if root_str is None:
            self._json_error(400, "root parameter is required")
            return

        depth = _int_param(params, "depth", default=10)

        root_node = self.cpg.node(NodeId(root_str))
        if root_node is None:
            self._json_error(404, f"Node not found: {root_str!r}")
            return

        sub = self.cpg.query().subgraph(NodeId(root_str), max_depth=depth)
        self._json_response(sub.to_dict())

    def _json_response(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status: int, message: str) -> None:
        self._json_response({"error": message}, status)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Silence default per-request stdout noise.
        pass


def _node_to_dict(node: Any, cpg: Any) -> dict[str, Any]:
    """Serialize a CpgNode to a plain dict, including annotations."""
    loc = node.location
    return {
        "id": str(node.id),
        "kind": node.kind.value,
        "name": node.name,
        "file": str(loc.file) if loc else None,
        "line": loc.line if loc else None,
        "column": loc.column if loc else None,
        "scope": str(node.scope) if node.scope is not None else None,
        "attrs": node.attrs,
        "annotations": cpg.annotations_for(node.id),
    }


def _first(params: dict[str, list[str]], key: str) -> str | None:
    """Return the first value for *key* from parse_qs output, or None."""
    vals = params.get(key)
    return vals[0] if vals else None


def _int_param(params: dict[str, list[str]], key: str, default: int) -> int:
    """Parse an integer query parameter, returning *default* on missing/invalid."""
    raw = _first(params, key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def run_cmd(args: argparse.Namespace, _cfg: Config | None = None) -> int:
    cpg_path: Path = args.cpg_file
    if not cpg_path.is_file():
        print(f"Error: CPG file not found: {cpg_path}", file=sys.stderr)
        return 1

    try:
        cpg = load_cpg(cpg_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading CPG: {exc}", file=sys.stderr)
        return 1

    CPGHandler.cpg = cpg

    host: str = args.host
    port: int = args.port
    server = HTTPServer((host, port), CPGHandler)

    print(
        f"Serving CPG ({cpg.node_count} nodes, {cpg.edge_count} edges)"
        f" at http://{host}:{port}",
        file=sys.stderr,
    )
    print("Endpoints: /health /info /query /node/<id> /edges /subgraph", file=sys.stderr)
    print("Press Ctrl+C to stop", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.", file=sys.stderr)
        server.server_close()

    return 0
