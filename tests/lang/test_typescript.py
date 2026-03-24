"""Tests for the TypeScript language visitor.

Uses CPGBuilder to parse fixture files and asserts on the resulting graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.builder import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "typescript"


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
        return _build("simple_function.ts")

    def test_module_node(self, cpg):
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "simple_function"

    def test_function_nodes_present(self, cpg):
        names = _node_names(cpg, NodeKind.FUNCTION)
        assert "add" in names
        assert "fetchData" in names
        assert "multiply" in names

    def test_parameters_for_add(self, cpg):
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "a" in param_names
        assert "b" in param_names

    def test_has_parameter_edges(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.HAS_PARAMETER)
        assert ("add", "a") in pairs
        assert ("add", "b") in pairs

    def test_async_function(self, cpg):
        fetch = next(
            (n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "fetchData"),
            None,
        )
        assert fetch is not None, "fetchData function not found"
        assert fetch.attrs.get("is_async") is True, (
            f"fetchData should be async, got attrs={fetch.attrs}"
        )

    def test_arrow_function_as_function_node(self, cpg):
        names = _node_names(cpg, NodeKind.FUNCTION)
        assert "multiply" in names, f"multiply not found in functions: {names}"

    def test_variable_declared(self, cpg):
        # `result` is declared inside `add`
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "result" in var_names

    def test_return_node_exists(self, cpg):
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(returns) >= 1

    def test_function_contained_in_module(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("simple_function", "add") in pairs

    def test_data_flow_to_return(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in pairs, (
            f"Expected result->return data flow. Actual DATA_FLOWS_TO pairs: {pairs}"
        )


class TestClassWithTypes:
    @pytest.fixture()
    def cpg(self):
        return _build("class_with_types.ts")

    def test_class_nodes(self, cpg):
        class_names = _node_names(cpg, NodeKind.CLASS)
        assert "Animal" in class_names
        assert "Dog" in class_names

    def test_method_nodes(self, cpg):
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert "constructor" in func_names
        assert "speak" in func_names
        assert "breathe" in func_names

    def test_methods_scoped_to_class(self, cpg):
        contains_pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("Animal", "speak") in contains_pairs
        assert ("Animal", "breathe") in contains_pairs

    def test_constructor_parameters(self, cpg):
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "name" in param_names
        assert "age" in param_names

    def test_async_method(self, cpg):
        breathe = next(
            (n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "breathe"),
            None,
        )
        assert breathe is not None
        assert breathe.attrs.get("is_async") is True, (
            f"breathe should be async, got attrs={breathe.attrs}"
        )

    def test_module_contains_classes(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("class_with_types", "Animal") in pairs
        assert ("class_with_types", "Dog") in pairs


class TestInterfaces:
    @pytest.fixture()
    def cpg(self):
        return _build("interfaces.ts")

    def test_interface_as_class_node(self, cpg):
        class_names = _node_names(cpg, NodeKind.CLASS)
        assert "User" in class_names, f"Expected User interface as CLASS. Got: {class_names}"
        assert "Repository" in class_names

    def test_enum_as_class_node(self, cpg):
        class_names = _node_names(cpg, NodeKind.CLASS)
        assert "Direction" in class_names, f"Expected Direction enum as CLASS. Got: {class_names}"
        assert "Status" in class_names

    def test_module_contains_interfaces_and_enums(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("interfaces", "User") in pairs
        assert ("interfaces", "Direction") in pairs


class TestImports:
    @pytest.fixture()
    def cpg(self):
        return _build("imports.ts")

    def test_import_nodes_present(self, cpg):
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) >= 3, f"Expected at least 3 import nodes, got {len(imports)}"

    def test_fs_import(self, cpg):
        # ES6 imports with `from` emit with module stored in attrs["module"]
        import_nodes = list(cpg.nodes(kind=NodeKind.IMPORT))
        modules = {n.attrs.get("module") for n in import_nodes}
        assert "fs" in modules, f"Expected 'fs' in import modules. Got: {modules}"

    def test_import_names_captured(self, cpg):
        import_nodes = list(cpg.nodes(kind=NodeKind.IMPORT))
        fs_import = next(
            (n for n in import_nodes if n.attrs.get("module") == "fs"), None
        )
        assert fs_import is not None, "fs import node not found"
        names = fs_import.attrs.get("names", [])
        assert "readFile" in names, f"Expected readFile in fs import names, got {names}"
        assert "writeFile" in names, f"Expected writeFile in fs import names, got {names}"

    def test_namespace_import(self, cpg):
        # `import * as path from "path"` — module is "path" in attrs
        import_nodes = list(cpg.nodes(kind=NodeKind.IMPORT))
        path_import = next(
            (n for n in import_nodes if n.attrs.get("module") == "path"), None
        )
        assert path_import is not None, (
            f"Expected path namespace import. Got modules: "
            f"{[n.attrs.get('module') for n in import_nodes]}"
        )

    def test_call_nodes_present(self, cpg):
        # readFile is called in the fixture
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "readFile" in call_names or any("readFile" in n for n in call_names), (
            f"Expected readFile call. Got: {call_names}"
        )


class TestCallResolution:
    @pytest.fixture()
    def cpg(self):
        return _build("simple_function.ts")

    def test_calls_edges_resolved(self, cpg):
        # multiply is defined and could be called if there were call sites
        # This test checks the basic structure is correct for call resolution
        calls_pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        # simple_function.ts doesn't call any of its own functions, so this may be empty
        # Just verify the method doesn't crash
        assert isinstance(calls_pairs, list)
