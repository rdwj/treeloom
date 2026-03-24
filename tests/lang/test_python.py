"""Tests for the Python language visitor.

Uses CPGBuilder to parse fixture files and asserts on the resulting graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.builder import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "python"


def _build(fixture_name: str) -> CodePropertyGraph:
    """Build a CPG from a single fixture file."""
    return CPGBuilder().add_file(FIXTURES / fixture_name).build()


def _node_names(cpg, kind: NodeKind) -> set[str]:
    return {n.name for n in cpg.nodes(kind=kind)}


def _edge_pairs(cpg, kind: EdgeKind) -> list[tuple[str, str]]:
    """Return (source_name, target_name) pairs for edges of a given kind."""
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
        return _build("simple_function.py")

    def test_module_node(self, cpg):
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "simple_function"

    def test_function_node(self, cpg):
        assert _node_names(cpg, NodeKind.FUNCTION) == {"add"}

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
        """The variable 'result' should flow to the return node."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in pairs


class TestClassWithMethods:
    @pytest.fixture()
    def cpg(self):
        return _build("class_with_methods.py")

    def test_class_node(self, cpg):
        assert _node_names(cpg, NodeKind.CLASS) == {"Calculator"}

    def test_methods(self, cpg):
        assert _node_names(cpg, NodeKind.FUNCTION) == {"__init__", "add", "reset"}

    def test_class_contains_methods(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("Calculator", "__init__") in pairs
        assert ("Calculator", "add") in pairs
        assert ("Calculator", "reset") in pairs

    def test_method_scoped_to_class(self, cpg):
        for fn in cpg.nodes(kind=NodeKind.FUNCTION):
            scope = cpg.scope_of(fn.id)
            assert scope is not None
            assert scope.kind == NodeKind.CLASS
            assert scope.name == "Calculator"

    def test_parameters_exclude_self(self, cpg):
        """'self' should be excluded from parameter nodes."""
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "self" not in param_names
        assert "value" in param_names
        assert "n" in param_names


class TestFunctionCalls:
    @pytest.fixture()
    def cpg(self):
        return _build("function_calls.py")

    def test_call_nodes(self, cpg):
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "greet" in call_names
        assert "print" in call_names

    def test_call_resolution(self, cpg):
        """greet() call should resolve to greet() definition."""
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("greet", "greet") in pairs

    def test_data_flow_arg_to_call(self, cpg):
        """Variable 'msg' should flow to the print() call."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("msg", "print") in pairs


class TestImports:
    @pytest.fixture()
    def cpg(self):
        return _build("imports.py")

    def test_import_count(self, cpg):
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) == 4

    @pytest.mark.parametrize(
        "module_name,is_from,expected_names",
        [
            ("os", False, ["os"]),
            ("pathlib", True, ["Path"]),
            ("sys", False, ["sys"]),
            ("collections", True, ["OrderedDict", "defaultdict"]),
        ],
    )
    def test_import_attrs(self, cpg, module_name, is_from, expected_names):
        matches = [
            n
            for n in cpg.nodes(kind=NodeKind.IMPORT)
            if n.attrs.get("module") == module_name
            and n.attrs.get("is_from") == is_from
        ]
        assert len(matches) == 1, f"Expected one import for {module_name}, got {len(matches)}"
        assert matches[0].attrs["names"] == expected_names


class TestControlFlow:
    @pytest.fixture()
    def cpg(self):
        return _build("control_flow.py")

    def test_function_exists(self, cpg):
        assert _node_names(cpg, NodeKind.FUNCTION) == {"check"}

    def test_call_nodes(self, cpg):
        """All print() calls and range() call should be present."""
        call_names = sorted(n.name for n in cpg.nodes(kind=NodeKind.CALL))
        assert call_names.count("print") == 4  # 3 in if + 1 in for loop
        assert "range" in call_names

    def test_loop_variable(self, cpg):
        """The for-loop variable 'i' should be emitted."""
        assert "i" in _node_names(cpg, NodeKind.VARIABLE)


class TestDataFlow:
    @pytest.fixture()
    def cpg(self):
        return _build("data_flow.py")

    def test_functions(self, cpg):
        assert _node_names(cpg, NodeKind.FUNCTION) == {"process", "pipeline"}

    def test_variable_chain(self, cpg):
        """Variables in the process function form a chain."""
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "cleaned" in var_names
        assert "upper" in var_names

    def test_data_flows_to_return(self, cpg):
        """'upper' flows to return in the process function."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # upper -> return (via the identifier reference in return statement)
        assert any(src == "upper" and tgt == "return" for src, tgt in pairs)


class TestBranchAndLoopNodes:
    """Verify that BRANCH and LOOP structural nodes are emitted."""

    @pytest.fixture()
    def cpg(self):
        return _build("control_flow.py")

    def test_branch_node_emitted(self, cpg):
        branches = list(cpg.nodes(kind=NodeKind.BRANCH))
        # if + elif = 2 branch nodes
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

    def test_for_loop_node_emitted(self, cpg):
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "for"
        ]
        assert len(loops) == 1
        assert loops[0].attrs["iterator_var"] == "i"

    def test_while_loop_node_emitted(self, cpg):
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "while"
        ]
        assert len(loops) == 1

    def test_branch_contained_in_function(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        # The "if" branch should be contained in the "check" function
        assert ("check", "if") in pairs

    def test_loop_contained_in_function(self, cpg):
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("check", "for") in pairs
        assert ("check", "while") in pairs


class TestUsedByEdges:
    """Verify that USED_BY edges are emitted for variable references."""

    @pytest.fixture()
    def cpg(self):
        return _build("function_calls.py")

    def test_used_by_in_call_arg(self, cpg):
        """Variable 'msg' should have a USED_BY edge to the print call."""
        pairs = _edge_pairs(cpg, EdgeKind.USED_BY)
        assert ("msg", "print") in pairs

    def test_used_by_in_return(self):
        """Variable 'result' should have USED_BY to return in simple_function."""
        cpg = _build("simple_function.py")
        pairs = _edge_pairs(cpg, EdgeKind.USED_BY)
        assert ("result", "return") in pairs


class TestCallResolutionDuplicateNames:
    """resolve_calls must handle multiple functions with the same name."""

    def test_both_functions_reachable(self):
        """Both Calculator.add and standalone add should exist."""
        source = b"""
class Calculator:
    def add(self, n):
        return n

def add(x, y):
    return x + y

def main():
    c = Calculator()
    c.add(1)
    add(2, 3)
"""
        cpg = CPGBuilder().add_source(source, "dup_names.py").build()
        func_names = [n.name for n in cpg.nodes(kind=NodeKind.FUNCTION)]
        assert func_names.count("add") == 2

    def test_calls_resolved_despite_duplicates(self):
        """Both calls should resolve (even if to the same best-effort match)."""
        source = b"""
def add(x, y):
    return x + y

def also_add(a, b):
    return add(a, b)
"""
        cpg = CPGBuilder().add_source(source, "dup2.py").build()
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("add", "add") in pairs


class TestAugmentedAssignment:
    @pytest.fixture()
    def cpg(self):
        return _build("augmented_assignment.py")

    def test_augmented_variable_emitted(self, cpg):
        assert "total" in _node_names(cpg, NodeKind.VARIABLE)

    def test_function_exists(self, cpg):
        assert "accumulate" in _node_names(cpg, NodeKind.FUNCTION)

    def test_loop_node_emitted(self, cpg):
        loops = list(cpg.nodes(kind=NodeKind.LOOP))
        assert len(loops) == 1
        assert loops[0].attrs["loop_type"] == "for"
        assert loops[0].attrs["iterator_var"] == "item"


class TestAddSource:
    def test_add_source_with_language(self):
        source = b"def hello(): pass"
        cpg = CPGBuilder().add_source(source, "test.py", "python").build()
        assert _node_names(cpg, NodeKind.FUNCTION) == {"hello"}

    def test_add_source_by_extension(self):
        source = b"x = 1"
        cpg = CPGBuilder().add_source(source, "test.py").build()
        assert _node_names(cpg, NodeKind.VARIABLE) == {"x"}


class TestAddDirectory:
    def test_add_directory(self):
        cpg = CPGBuilder().add_directory(FIXTURES).build()
        modules = _node_names(cpg, NodeKind.MODULE)
        assert "simple_function" in modules
        assert "class_with_methods" in modules
        assert "function_calls" in modules

    def test_files_property(self):
        cpg = CPGBuilder().add_directory(FIXTURES).build()
        assert len(cpg.files) >= 6
