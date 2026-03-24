"""Tests for the JavaScript language visitor.

Uses CPGBuilder to parse fixture files and asserts on the resulting graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.builder import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "javascript"


def _build(fixture_name: str) -> CodePropertyGraph:
    return CPGBuilder().add_file(FIXTURES / fixture_name).build()


def _node_names(cpg: CodePropertyGraph, kind: NodeKind) -> set[str]:
    return {n.name for n in cpg.nodes(kind=kind)}


def _edge_pairs(cpg: CodePropertyGraph, kind: EdgeKind) -> list[tuple[str, str]]:
    pairs = []
    for e in cpg.edges(kind=kind):
        src = cpg.node(e.source)
        tgt = cpg.node(e.target)
        if src and tgt:
            pairs.append((src.name, tgt.name))
    return pairs


class TestSimpleFunction:
    @pytest.fixture()
    def cpg(self):
        return _build("simple_function.js")

    def test_module_node(self, cpg):
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "simple_function"

    def test_function_node(self, cpg):
        assert "add" in _node_names(cpg, NodeKind.FUNCTION)

    def test_parameter_nodes(self, cpg):
        assert _node_names(cpg, NodeKind.PARAMETER) == {"x", "y"}

    def test_has_parameter_edges(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.HAS_PARAMETER)
        assert ("add", "x") in pairs
        assert ("add", "y") in pairs

    def test_variable_node(self, cpg):
        assert "result" in _node_names(cpg, NodeKind.VARIABLE)

    def test_return_node(self, cpg):
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(returns) == 1

    def test_function_contained_in_module(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("simple_function", "add") in pairs

    def test_variable_contained_in_function(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("add", "result") in pairs

    def test_data_flow_to_return(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in pairs


class TestClassWithMethods:
    @pytest.fixture()
    def cpg(self):
        return _build("class_with_methods.js")

    def test_class_node(self, cpg):
        assert _node_names(cpg, NodeKind.CLASS) == {"Calculator"}

    def test_methods(self, cpg):
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert "constructor" in func_names
        assert "add" in func_names
        assert "reset" in func_names

    def test_class_contains_methods(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("Calculator", "constructor") in pairs
        assert ("Calculator", "add") in pairs
        assert ("Calculator", "reset") in pairs

    def test_method_scoped_to_class(self, cpg):
        for fn in cpg.nodes(kind=NodeKind.FUNCTION):
            scope = cpg.scope_of(fn.id)
            assert scope is not None
            assert scope.kind == NodeKind.CLASS
            assert scope.name == "Calculator"

    def test_constructor_parameter(self, cpg):
        assert "initial" in _node_names(cpg, NodeKind.PARAMETER)


class TestArrowFunctions:
    @pytest.fixture()
    def cpg(self):
        return _build("arrow_functions.js")

    def test_arrow_function_nodes(self, cpg):
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        # Arrow functions assigned to const get the variable name
        assert "double" in func_names
        assert "add" in func_names
        assert "greet" in func_names

    def test_arrow_parameters(self, cpg):
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "n" in param_names
        assert "x" in param_names
        assert "y" in param_names
        assert "name" in param_names

    def test_variable_in_arrow_body(self, cpg):
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "result" in var_names
        assert "msg" in var_names

    def test_return_nodes_emitted(self, cpg):
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        # add and greet both have explicit return statements
        assert len(returns) >= 2

    def test_data_flow_to_return(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in pairs
        assert ("msg", "return") in pairs


class TestImports:
    @pytest.fixture()
    def cpg(self):
        return _build("imports.js")

    def test_import_count(self, cpg):
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) == 3

    @pytest.mark.parametrize(
        "module_name,expected_names",
        [
            ("fs", ["readFile", "writeFile"]),
            ("path", ["path"]),
            ("events", ["EventEmitter"]),
        ],
    )
    def test_import_attrs(self, cpg, module_name, expected_names):
        matches = [
            n
            for n in cpg.nodes(kind=NodeKind.IMPORT)
            if n.attrs.get("module") == module_name
        ]
        assert len(matches) == 1, (
            f"Expected one import for {module_name!r}, got {len(matches)}"
        )
        assert matches[0].attrs["names"] == expected_names, (
            f"names mismatch for {module_name!r}: {matches[0].attrs['names']!r}"
        )


class TestControlFlow:
    @pytest.fixture()
    def cpg(self):
        return _build("control_flow.js")

    def test_function_exists(self, cpg):
        assert "check" in _node_names(cpg, NodeKind.FUNCTION)

    def test_call_nodes(self, cpg):
        call_names = list(n.name for n in cpg.nodes(kind=NodeKind.CALL))
        # console.log appears multiple times
        assert call_names.count("console.log") >= 4

    def test_branch_nodes_emitted(self, cpg):
        branches = list(cpg.nodes(kind=NodeKind.BRANCH))
        assert len(branches) >= 2
        branch_types = {b.attrs.get("branch_type") for b in branches}
        assert "if" in branch_types
        assert "elif" in branch_types

    def test_if_branch_has_else(self, cpg):
        if_branches = [
            b for b in cpg.nodes(kind=NodeKind.BRANCH)
            if b.attrs.get("branch_type") == "if"
        ]
        assert len(if_branches) == 1
        assert if_branches[0].attrs["has_else"] is True

    def test_for_loop_node(self, cpg):
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "for"
        ]
        assert len(loops) == 1
        assert loops[0].attrs["iterator_var"] == "i"

    def test_while_loop_node(self, cpg):
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "while"
        ]
        assert len(loops) == 1

    def test_loop_variable_emitted(self, cpg):
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "i" in var_names

    def test_branch_contained_in_function(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("check", "if") in pairs

    def test_loop_contained_in_function(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("check", "for") in pairs
        assert ("check", "while") in pairs


class TestCallResolution:
    def test_function_call_resolves(self):
        source = b"""
function add(x, y) {
    return x + y;
}
function main() {
    const r = add(1, 2);
}
"""
        cpg = CPGBuilder().add_source(source, "calls.js", "javascript").build()
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("add", "add") in pairs

    def test_data_flow_arg_to_call(self):
        source = b"""
function greet(name) {
    return name;
}
function main() {
    const msg = "world";
    greet(msg);
}
"""
        cpg = CPGBuilder().add_source(source, "df.js", "javascript").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("msg", "greet") in pairs


class TestAddSource:
    def test_add_source_with_language(self):
        source = b"function hello() { return 1; }"
        cpg = CPGBuilder().add_source(source, "test.js", "javascript").build()
        assert "hello" in _node_names(cpg, NodeKind.FUNCTION)

    def test_add_source_by_extension(self):
        source = b"const x = 42;"
        cpg = CPGBuilder().add_source(source, "test.js").build()
        assert "x" in _node_names(cpg, NodeKind.VARIABLE)


class TestRegistryIntegration:
    def test_js_extension_registered(self):
        from treeloom.lang.registry import LanguageRegistry

        reg = LanguageRegistry.default()
        assert ".js" in reg.supported_extensions()
        assert ".mjs" in reg.supported_extensions()
        assert ".cjs" in reg.supported_extensions()

    def test_visitor_by_name(self):
        from treeloom.lang.registry import LanguageRegistry

        reg = LanguageRegistry.default()
        visitor = reg.get_visitor_by_name("javascript")
        assert visitor is not None
        assert visitor.name == "javascript"
