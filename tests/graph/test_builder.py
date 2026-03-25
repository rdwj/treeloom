"""Tests for CPGBuilder and its NodeEmitter implementation."""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.builder import CPGBuilder
from treeloom.model.edges import EdgeKind
from treeloom.model.location import SourceLocation
from treeloom.model.nodes import NodeKind


@pytest.fixture()
def builder() -> CPGBuilder:
    """A builder with no registry (emitter-only testing)."""
    return CPGBuilder(registry=None)


class TestNodeIdGeneration:
    def test_id_format(self, builder: CPGBuilder):
        node_id = builder.emit_module("test", Path("test.py"))
        id_str = str(node_id)
        assert id_str.startswith("module:")
        assert "test.py" in id_str
        assert ":1:" in id_str  # line 1

    def test_ids_are_unique(self, builder: CPGBuilder):
        id1 = builder.emit_module("a", Path("a.py"))
        id2 = builder.emit_module("b", Path("b.py"))
        assert id1 != id2

    def test_counter_increments(self, builder: CPGBuilder):
        id1 = builder.emit_module("a", Path("a.py"))
        id2 = builder.emit_module("b", Path("b.py"))
        # Extract counter (last segment)
        c1 = int(str(id1).rsplit(":", 1)[-1])
        c2 = int(str(id2).rsplit(":", 1)[-1])
        assert c2 > c1


class TestEmitModule:
    def test_emit_module(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        cpg = builder._cpg
        node = cpg.node(mod_id)
        assert node is not None
        assert node.kind == NodeKind.MODULE
        assert node.name == "test"
        assert node.scope is None


class TestEmitFunction:
    def test_emit_function(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=5, column=0)
        fn_id = builder.emit_function("my_func", loc, mod_id)

        cpg = builder._cpg
        fn = cpg.node(fn_id)
        assert fn is not None
        assert fn.kind == NodeKind.FUNCTION
        assert fn.name == "my_func"
        assert fn.scope == mod_id

    def test_emit_function_creates_contains_edge(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=5, column=0)
        fn_id = builder.emit_function("f", loc, mod_id)

        contains = list(builder._cpg.edges(kind=EdgeKind.CONTAINS))
        assert any(e.source == mod_id and e.target == fn_id for e in contains)

    def test_emit_function_with_params(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=5, column=0)
        fn_id = builder.emit_function("f", loc, mod_id, params=["a", "b"])

        params = list(builder._cpg.nodes(kind=NodeKind.PARAMETER))
        assert len(params) == 2
        names = {p.name for p in params}
        assert names == {"a", "b"}

        # HAS_PARAMETER edges
        hp_edges = list(builder._cpg.edges(kind=EdgeKind.HAS_PARAMETER))
        assert len(hp_edges) == 2
        assert all(e.source == fn_id for e in hp_edges)

    def test_async_function(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=1, column=0)
        fn_id = builder.emit_function("f", loc, mod_id, is_async=True)
        fn = builder._cpg.node(fn_id)
        assert fn is not None
        assert fn.attrs["is_async"] is True


class TestEmitVariable:
    def test_emit_variable(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=3, column=0)
        var_id = builder.emit_variable("x", loc, mod_id)

        node = builder._cpg.node(var_id)
        assert node is not None
        assert node.kind == NodeKind.VARIABLE
        assert node.name == "x"
        assert node.scope == mod_id

    def test_emit_variable_creates_contains_edge(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=3, column=0)
        var_id = builder.emit_variable("x", loc, mod_id)

        contains = list(builder._cpg.edges(kind=EdgeKind.CONTAINS))
        assert any(e.source == mod_id and e.target == var_id for e in contains)


class TestEmitCall:
    def test_emit_call(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=5, column=0)
        call_id = builder.emit_call("print", loc, mod_id, args=["x"])

        node = builder._cpg.node(call_id)
        assert node is not None
        assert node.kind == NodeKind.CALL
        assert node.name == "print"
        assert node.attrs["args_count"] == 1


class TestEmitLiteral:
    def test_emit_literal(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=1, column=0)
        lit_id = builder.emit_literal("42", "int", loc, mod_id)

        node = builder._cpg.node(lit_id)
        assert node is not None
        assert node.kind == NodeKind.LITERAL
        assert node.attrs["literal_type"] == "int"
        assert node.attrs["raw_value"] == "42"


class TestEmitReturn:
    def test_emit_return(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=10, column=4)
        ret_id = builder.emit_return(loc, mod_id)

        node = builder._cpg.node(ret_id)
        assert node is not None
        assert node.kind == NodeKind.RETURN
        assert node.name == "return"


class TestEmitImport:
    def test_emit_import(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=1, column=0)
        imp_id = builder.emit_import("os", ["path"], loc, mod_id, is_from=True)

        node = builder._cpg.node(imp_id)
        assert node is not None
        assert node.kind == NodeKind.IMPORT
        assert node.attrs["module"] == "os"
        assert node.attrs["names"] == ["path"]
        assert node.attrs["is_from"] is True


class TestDataFlowEdges:
    def test_emit_data_flow(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=1, column=0)
        v1 = builder.emit_variable("a", loc, mod_id)
        v2 = builder.emit_variable("b", loc, mod_id)
        builder.emit_data_flow(v1, v2)

        df_edges = list(builder._cpg.edges(kind=EdgeKind.DATA_FLOWS_TO))
        assert len(df_edges) == 1
        assert df_edges[0].source == v1
        assert df_edges[0].target == v2

    def test_emit_definition(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=1, column=0)
        var = builder.emit_variable("x", loc, mod_id)
        lit = builder.emit_literal("5", "int", loc, mod_id)
        builder.emit_definition(var, lit)

        edges = list(builder._cpg.edges(kind=EdgeKind.DEFINED_BY))
        assert len(edges) == 1
        assert edges[0].source == var
        assert edges[0].target == lit

    def test_emit_usage(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=1, column=0)
        var = builder.emit_variable("x", loc, mod_id)
        call = builder.emit_call("print", loc, mod_id, args=["x"])
        builder.emit_usage(var, call)

        edges = list(builder._cpg.edges(kind=EdgeKind.USED_BY))
        assert len(edges) == 1
        assert edges[0].source == var
        assert edges[0].target == call


class TestControlFlowEdges:
    def test_emit_control_flow(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=1, column=0)
        v1 = builder.emit_variable("a", loc, mod_id)
        v2 = builder.emit_variable("b", loc, mod_id)
        builder.emit_control_flow(v1, v2)

        edges = list(builder._cpg.edges(kind=EdgeKind.FLOWS_TO))
        assert len(edges) == 1

    def test_emit_branch(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        loc = SourceLocation(file=Path("test.py"), line=1, column=0)
        cond = builder.emit_variable("cond", loc, mod_id)
        t_branch = builder.emit_variable("then", loc, mod_id)
        f_branch = builder.emit_variable("else", loc, mod_id)
        builder.emit_branch(cond, t_branch, f_branch)

        edges = list(builder._cpg.edges(kind=EdgeKind.BRANCHES_TO))
        assert len(edges) == 2


class TestBuild:
    def test_build_returns_cpg(self, builder: CPGBuilder):
        builder.emit_module("test", Path("test.py"))
        cpg = builder.build()
        assert cpg.node_count == 1

    def test_build_clears_tree_nodes(self, builder: CPGBuilder):
        mod_id = builder.emit_module("test", Path("test.py"))
        # Manually set a fake tree node
        builder._cpg.node(mod_id)._tree_node = "fake"
        cpg = builder.build()
        assert cpg.node(mod_id)._tree_node is None
