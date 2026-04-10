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

    def test_aliased_import_records_alias(self, cpg):
        """``import sys as system`` should record aliases={"sys": "system"}."""
        sys_imports = [
            n for n in cpg.nodes(kind=NodeKind.IMPORT)
            if n.attrs.get("module") == "sys" and not n.attrs.get("is_from")
        ]
        assert len(sys_imports) == 1
        assert sys_imports[0].attrs.get("aliases") == {"sys": "system"}

    def test_unaliased_import_has_no_aliases(self, cpg):
        """``import os`` (no alias) should have no ``aliases`` key in attrs."""
        os_imports = [
            n for n in cpg.nodes(kind=NodeKind.IMPORT)
            if n.attrs.get("module") == "os" and not n.attrs.get("is_from")
        ]
        assert len(os_imports) == 1
        assert "aliases" not in os_imports[0].attrs

    def test_from_import_without_alias_has_no_aliases(self, cpg):
        """``from collections import OrderedDict, defaultdict`` has no aliases."""
        collections_imports = [
            n for n in cpg.nodes(kind=NodeKind.IMPORT)
            if n.attrs.get("module") == "collections"
        ]
        assert len(collections_imports) == 1
        assert "aliases" not in collections_imports[0].attrs


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


class TestNestedScopes:
    """Verify that nested functions produce separate variable scopes."""

    @pytest.fixture()
    def cpg(self):
        return _build("nested_scopes.py")

    def test_outer_and_inner_both_have_x(self, cpg):
        """Both outer and inner should have their own VARIABLE node for 'x'."""
        x_vars = [n for n in cpg.nodes(kind=NodeKind.VARIABLE) if n.name == "x"]
        assert len(x_vars) == 2, (
            f"Expected 2 VARIABLE nodes named 'x' (outer + inner), got {len(x_vars)}"
        )

    def test_outer_return_flows_from_outer_x(self, cpg):
        """'return x' in outer() should flow from outer's x, not inner's x."""
        # The outer function's return should get data flow from the outer x
        outer_func = next(
            n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "outer"
        )
        # Get all x variable nodes and figure out which is in outer scope
        x_vars = [n for n in cpg.nodes(kind=NodeKind.VARIABLE) if n.name == "x"]
        outer_x_nodes = [
            v for v in x_vars
            if cpg.scope_of(v.id) is not None
            and cpg.scope_of(v.id).id == outer_func.id
        ]
        assert len(outer_x_nodes) >= 1, "Expected at least one 'x' scoped to outer()"

        # The return node in outer should have data flow from an outer x
        returns_in_outer = [
            n for n in cpg.nodes(kind=NodeKind.RETURN)
            if cpg.scope_of(n.id) is not None
            and cpg.scope_of(n.id).id == outer_func.id
        ]
        assert len(returns_in_outer) == 1, "Expected one RETURN in outer()"

        # Check DATA_FLOWS_TO edges reaching the return node
        ret_predecessors = cpg.predecessors(
            returns_in_outer[0].id, edge_kind=EdgeKind.DATA_FLOWS_TO
        )
        pred_ids = {p.id for p in ret_predecessors}
        outer_x_ids = {v.id for v in outer_x_nodes}
        assert pred_ids & outer_x_ids, (
            "outer()'s return should receive data flow from outer's x, "
            f"but predecessors are {[p.name for p in ret_predecessors]}"
        )

    def test_shadowing_dangerous_gets_outer_data(self, cpg):
        """dangerous(data) in shadowing() should wire to outer 'data', not inner's."""
        shadowing_func = next(
            n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "shadowing"
        )
        # Find the dangerous() call
        dangerous_calls = [
            n for n in cpg.nodes(kind=NodeKind.CALL)
            if n.name == "dangerous"
        ]
        assert len(dangerous_calls) == 1

        # The argument to dangerous should be the outer 'data' variable
        predecessors = cpg.predecessors(
            dangerous_calls[0].id, edge_kind=EdgeKind.DATA_FLOWS_TO
        )
        pred_names = {p.name for p in predecessors}
        assert "data" in pred_names, (
            f"dangerous() should receive data flow from 'data', got {pred_names}"
        )

        # Verify the data variable is scoped to shadowing(), not helper()
        data_preds = [p for p in predecessors if p.name == "data"]
        for dp in data_preds:
            scope = cpg.scope_of(dp.id)
            assert scope is not None
            assert scope.id == shadowing_func.id, (
                f"'data' flowing to dangerous() should be scoped to shadowing(), "
                f"but is scoped to {scope.name}"
            )

    def test_inner_process_gets_inner_data(self, cpg):
        """process(data) inside helper() should wire to inner 'data'."""
        helper_func = next(
            n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "helper"
        )
        process_calls = [
            n for n in cpg.nodes(kind=NodeKind.CALL) if n.name == "process"
        ]
        assert len(process_calls) == 1

        predecessors = cpg.predecessors(
            process_calls[0].id, edge_kind=EdgeKind.DATA_FLOWS_TO
        )
        data_preds = [p for p in predecessors if p.name == "data"]
        assert len(data_preds) >= 1, "process() should receive data flow from 'data'"

        for dp in data_preds:
            scope = cpg.scope_of(dp.id)
            assert scope is not None
            assert scope.id == helper_func.id, (
                f"'data' flowing to process() should be scoped to helper(), "
                f"but is scoped to {scope.name}"
            )


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


class TestStringFormattingDataFlow:
    """Data flow through .format(), %, and f-string operations."""

    @pytest.fixture()
    def cpg(self):
        return _build("string_formatting.py")

    def test_format_args_flow_to_call(self, cpg):
        """format() args should have DATA_FLOWS_TO the format call node."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        fmt_calls = [
            n for n in cpg.nodes(kind=NodeKind.CALL)
            if "format" in n.name
        ]
        assert fmt_calls, "Expected at least one .format() call node"
        # username and password should flow into a format call
        fmt_targets = {c.name for c in fmt_calls}
        param_to_fmt = [
            (src, tgt) for src, tgt in pairs
            if tgt in fmt_targets and src in ("username", "password")
        ]
        assert len(param_to_fmt) >= 2, (
            f"Expected username+password to flow to .format() call, got {param_to_fmt}"
        )

    def test_format_result_flows_to_variable(self, cpg):
        """The .format() call result should flow to the 'query' variable."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        fmt_to_var = [
            (src, tgt) for src, tgt in pairs
            if "format" in src and tgt == "query"
        ]
        assert fmt_to_var, "Expected .format() call to flow to 'query' variable"

    def test_percent_format_flows_to_variable(self, cpg):
        """`%` formatting should create data flow from the operand."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # username -> % pseudo-call -> query
        pct_to_var = [(s, t) for s, t in pairs if s == "%" and t == "query"]
        assert pct_to_var, "Expected % pseudo-call to flow to 'query'"
        arg_to_pct = [(s, t) for s, t in pairs if s == "username" and t == "%"]
        assert arg_to_pct, "Expected 'username' to flow to % pseudo-call"

    def test_fstring_interpolation_flows(self, cpg):
        """f-string interpolated variables should flow to the f-string node."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        fstr_to_var = [(s, t) for s, t in pairs if s == "f-string" and t == "query"]
        assert fstr_to_var, "Expected f-string node to flow to 'query'"
        arg_to_fstr = [(s, t) for s, t in pairs if s == "username" and t == "f-string"]
        assert arg_to_fstr, "Expected 'username' to flow to f-string node"

    def test_nested_format_chains_to_outer_call(self, cpg):
        """`.format()` nested inside c.execute() should chain data flow."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        fmt_to_exec = [
            (src, tgt) for src, tgt in pairs
            if "format" in src and "execute" in tgt
        ]
        assert fmt_to_exec, (
            "Expected .format() result to flow to c.execute() call"
        )

    def test_percent_tuple_both_args_flow(self, cpg):
        """% with a tuple RHS should wire both tuple elements."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # Both username and password should flow to some % call
        user_to_pct = [(s, t) for s, t in pairs if s == "username" and t == "%"]
        pass_to_pct = [(s, t) for s, t in pairs if s == "password" and t == "%"]
        assert user_to_pct, "Expected 'username' to flow to % call in tuple case"
        assert pass_to_pct, "Expected 'password' to flow to % call in tuple case"


class TestParameterDataFlow:
    """Parameters should be resolvable as identifiers in expressions."""

    def test_param_flows_to_call_arg(self):
        """Parameter used as a call argument should create DATA_FLOWS_TO."""
        source = b"""
def process(data):
    return clean(data)
"""
        cpg = CPGBuilder().add_source(source, "param_flow.py").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("data", "clean") in pairs, (
            f"Expected parameter 'data' to flow to clean() call, "
            f"got DATA_FLOWS_TO pairs: {pairs}"
        )

    def test_param_flows_through_assignment(self):
        """Parameter assigned to a variable should create data flow chain."""
        source = b"""
def process(data):
    x = data
    return x
"""
        cpg = CPGBuilder().add_source(source, "param_assign.py").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("data", "x") in pairs, (
            f"Expected parameter 'data' to flow to variable 'x', "
            f"got DATA_FLOWS_TO pairs: {pairs}"
        )

    def test_param_flows_to_return(self):
        """Parameter used directly in return should flow to RETURN node."""
        source = b"""
def identity(x):
    return x
"""
        cpg = CPGBuilder().add_source(source, "param_ret.py").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("x", "return") in pairs, (
            f"Expected parameter 'x' to flow to return, "
            f"got DATA_FLOWS_TO pairs: {pairs}"
        )


class TestChainedMethodCalls:
    """Data flow through chained method calls such as obj.method1().method2()."""

    def test_format_fetchone_chain(self):
        """Data flows through .format().fetchone(): username -> format -> execute -> fetchone."""
        source = b"""
def query(username):
    result = c.execute("SELECT * WHERE u='{}'".format(username)).fetchone()
    return result
"""
        cpg = CPGBuilder().add_source(source, "chain_fetch.py").build()
        calls = {n.name for n in cpg.nodes(kind=NodeKind.CALL)}
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)

        # All three call nodes must exist
        format_calls = [n for n in cpg.nodes(kind=NodeKind.CALL) if "format" in n.name]
        execute_calls = [n for n in cpg.nodes(kind=NodeKind.CALL) if "execute" in n.name]
        fetchone_calls = [n for n in cpg.nodes(kind=NodeKind.CALL) if "fetchone" in n.name]
        assert format_calls, f"Expected a .format() call node, got calls: {calls}"
        assert execute_calls, f"Expected a .execute() call node, got calls: {calls}"
        assert fetchone_calls, f"Expected a .fetchone() call node, got calls: {calls}"

        # username flows into .format()
        fmt_name = format_calls[0].name
        assert ("username", fmt_name) in pairs, (
            f"Expected username -> {fmt_name!r}, got pairs: {pairs}"
        )

        # .format() result flows into .execute()
        exec_name = execute_calls[0].name
        assert (fmt_name, exec_name) in pairs, (
            f"Expected {fmt_name!r} -> {exec_name!r}, got pairs: {pairs}"
        )

        # .execute() result flows into .fetchone()
        fetch_name = fetchone_calls[0].name
        assert (exec_name, fetch_name) in pairs, (
            f"Expected {exec_name!r} -> {fetch_name!r}, got pairs: {pairs}"
        )

    def test_triple_chain(self):
        """Data flows through a three-level chain: transform(data).encode().decode()."""
        source = b"""
def process(data):
    result = transform(data).encode().decode()
    return result
"""
        cpg = CPGBuilder().add_source(source, "triple_chain.py").build()
        calls = {n.name for n in cpg.nodes(kind=NodeKind.CALL)}
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)

        # All three call nodes must exist
        transform_calls = [
            n for n in cpg.nodes(kind=NodeKind.CALL)
            if "transform" in n.name and "encode" not in n.name
        ]
        encode_calls = [n for n in cpg.nodes(kind=NodeKind.CALL) if "encode" in n.name]
        decode_calls = [n for n in cpg.nodes(kind=NodeKind.CALL) if "decode" in n.name]
        assert transform_calls, f"Expected a transform() call node, got: {calls}"
        assert encode_calls, f"Expected an .encode() call node, got: {calls}"
        assert decode_calls, f"Expected a .decode() call node, got: {calls}"

        # data flows into transform()
        xform_name = transform_calls[0].name
        assert ("data", xform_name) in pairs, (
            f"Expected data -> {xform_name!r}, got pairs: {pairs}"
        )

        # transform() result flows into .encode()
        enc_name = encode_calls[0].name
        assert (xform_name, enc_name) in pairs, (
            f"Expected {xform_name!r} -> {enc_name!r}, got pairs: {pairs}"
        )

        # .encode() result flows into .decode()
        dec_name = decode_calls[0].name
        assert (enc_name, dec_name) in pairs, (
            f"Expected {enc_name!r} -> {dec_name!r}, got pairs: {pairs}"
        )


class TestMethodReturnFlow:
    """Method call return values and attribute/subscript access should propagate
    DATA_FLOWS_TO through variable assignments."""

    @pytest.fixture()
    def cpg(self):
        return _build("method_return_flow.py")

    def test_method_call_result_flows_to_variable(self, cpg):
        """request.form.get() result should flow to the 'username' variable."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        method_to_var = [
            (s, t) for s, t in pairs if "get" in s and t == "username"
        ]
        assert method_to_var, (
            f"Expected method call result to flow to 'username', got pairs: {pairs}"
        )

    def test_variable_flows_to_next_call(self, cpg):
        """Variable 'username' should flow as argument to login()."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("username", "login") in pairs, (
            f"Expected 'username' -> 'login', got pairs: {pairs}"
        )

    def test_full_chain_call_result_to_variable_to_call(self, cpg):
        """Full chain: login() result -> result variable -> execute() call."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("login", "result") in pairs, (
            f"Expected 'login' -> 'result', got pairs: {pairs}"
        )
        assert ("result", "execute") in pairs, (
            f"Expected 'result' -> 'execute', got pairs: {pairs}"
        )

    def test_subscript_result_flows_to_variable(self, cpg):
        """config['database'] subscript result should flow to the 'data' variable."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # The subscript node name includes the full text, e.g. "config['database']"
        sub_to_var = [(s, t) for s, t in pairs if "config" in s and t == "data"]
        assert sub_to_var, (
            f"Expected subscript result to flow to 'data', got pairs: {pairs}"
        )

    def test_subscript_variable_flows_to_call(self, cpg):
        """Variable 'data' (from subscript) should flow to connect()."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("data", "connect") in pairs, (
            f"Expected 'data' -> 'connect', got pairs: {pairs}"
        )

    def test_attribute_access_flows_to_variable(self, cpg):
        """obj.attr should flow to the 'value' variable."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        attr_to_var = [(s, t) for s, t in pairs if "obj.attr" in s and t == "value"]
        assert attr_to_var, (
            f"Expected attribute access to flow to 'value', got pairs: {pairs}"
        )

    def test_chained_method_chain_preserved(self, cpg):
        """obj.method().strip() should chain: obj.method -> obj.method.strip -> value."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        method_calls = [
            n for n in cpg.nodes(kind=NodeKind.CALL) if "method" in n.name
        ]
        strip_calls = [
            n for n in cpg.nodes(kind=NodeKind.CALL) if "strip" in n.name
        ]
        assert method_calls, "Expected obj.method() call node"
        assert strip_calls, "Expected .strip() call node"

        method_name = method_calls[0].name
        strip_name = strip_calls[0].name
        assert (method_name, strip_name) in pairs, (
            f"Expected {method_name!r} -> {strip_name!r} in chained call, got pairs: {pairs}"
        )
        # strip result flows to value
        strip_to_var = [(s, t) for s, t in pairs if s == strip_name and t == "value"]
        assert strip_to_var, (
            f"Expected {strip_name!r} -> 'value', got pairs: {pairs}"
        )


class TestDecoratedDefinition:
    """Decorated function definitions should capture decorator names and still
    emit the wrapped function node correctly."""

    def test_decorator_names_in_attrs(self):
        """Decorator names should appear in the function's attrs['decorators']."""
        source = b"""
@app.route('/api/users/<username>', methods=['GET'])
def get_user(username):
    return username
"""
        cpg = CPGBuilder().add_source(source, "decorated.py").build()
        fns = list(cpg.nodes(kind=NodeKind.FUNCTION))
        assert len(fns) == 1, f"Expected 1 function, got {[f.name for f in fns]}"
        fn = fns[0]
        assert fn.name == "get_user"
        decorators = fn.attrs.get("decorators", [])
        assert any("route" in d for d in decorators), (
            f"Expected app.route decorator in attrs, got {decorators}"
        )

    def test_decorated_function_has_parameters(self):
        """Parameters of a decorated function should still be emitted."""
        source = b"""
@requires_auth
def update_user(username, data):
    pass
"""
        cpg = CPGBuilder().add_source(source, "decorated_params.py").build()
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "username" in param_names, f"Expected 'username' param, got {param_names}"
        assert "data" in param_names, f"Expected 'data' param, got {param_names}"

    def test_decorator_call_emitted_as_call_node(self):
        """The @app.route(...) decorator should be emitted as a CALL node."""
        source = b"""
@app.route('/api/books')
def get_books():
    pass
"""
        cpg = CPGBuilder().add_source(source, "decorated_call.py").build()
        call_names = _node_names(cpg, NodeKind.CALL)
        assert any("route" in c for c in call_names), (
            f"Expected app.route call node from decorator, got {call_names}"
        )

    def test_function_body_still_visited(self):
        """Calls inside a decorated function body should still be emitted."""
        source = b"""
@app.route('/api/items')
def get_items():
    return jsonify({'items': []})
"""
        cpg = CPGBuilder().add_source(source, "decorated_body.py").build()
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "jsonify" in call_names, (
            f"Expected jsonify call inside decorated function body, got {call_names}"
        )

    def test_multiple_decorators(self):
        """Multiple stacked decorators should all be captured."""
        source = b"""
@app.route('/api/admin')
@requires_auth
@admin_only
def admin_view():
    pass
"""
        cpg = CPGBuilder().add_source(source, "multi_decorator.py").build()
        fns = list(cpg.nodes(kind=NodeKind.FUNCTION))
        assert len(fns) == 1
        decorators = fns[0].attrs.get("decorators", [])
        assert len(decorators) == 3, f"Expected 3 decorators, got {decorators}"


class TestKeywordAndSplatArgs:
    """Keyword arguments and **kwargs splats should propagate taint to the call."""

    def test_keyword_arg_flows_to_call(self):
        """Data passed as a keyword argument should flow to the call site."""
        source = b"""
def register(request_data):
    user = User(username=request_data['username'], password=request_data['password'])
"""
        cpg = CPGBuilder().add_source(source, "kwarg_flow.py").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # request_data['username'] -> User call
        subscript_to_user = [
            (s, t) for s, t in pairs
            if "request_data" in s and t == "User"
        ]
        assert subscript_to_user, (
            f"Expected request_data subscript to flow to User() call via kwarg, "
            f"got DATA_FLOWS_TO pairs: {pairs}"
        )

    def test_dict_splat_flows_to_call(self):
        """**kwargs splat should flow the source dict into the call."""
        source = b"""
def create(request_data):
    user = User(**request_data)
"""
        cpg = CPGBuilder().add_source(source, "splat_flow.py").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        splat_to_call = [
            (s, t) for s, t in pairs
            if s == "request_data" and t == "User"
        ]
        assert splat_to_call, (
            f"Expected 'request_data' to flow to User() via ** splat, "
            f"got DATA_FLOWS_TO pairs: {pairs}"
        )


class TestComprehensionVisitation:
    """Calls inside comprehensions should be visited so the graph is complete."""

    def test_call_in_list_comprehension_iterable(self):
        """A call in the iterable of a list comprehension should be emitted."""
        source = b"""
def get_names():
    return [u.username for u in User.query.all()]
"""
        cpg = CPGBuilder().add_source(source, "comprehension.py").build()
        call_names = _node_names(cpg, NodeKind.CALL)
        assert any("all" in c for c in call_names), (
            f"Expected User.query.all() call inside comprehension, got {call_names}"
        )

    def test_call_in_generator_expression(self):
        """A call used inside a generator expression should be emitted."""
        source = b"""
def serialize(items):
    return list(str(x) for x in get_items())
"""
        cpg = CPGBuilder().add_source(source, "generator.py").build()
        call_names = _node_names(cpg, NodeKind.CALL)
        assert any("get_items" in c for c in call_names), (
            f"Expected get_items() call inside generator, got {call_names}"
        )


class TestChainedAttributeDFG:
    """Issue #51: chained attribute receivers should propagate data flow."""

    def test_request_form_get_chain(self):
        """request -> request.form -> request.form.get() should all be wired."""
        source = b"""
def handle(request):
    username = request.form.get('username')
    return username
"""
        cpg = CPGBuilder().add_source(source, "chained_attr.py").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)

        # request (param) should flow into request.form (attribute variable)
        req_to_form = [(s, t) for s, t in pairs if s == "request" and "form" in t]
        assert req_to_form, (
            f"Expected 'request' -> 'request.form', got DATA_FLOWS_TO pairs: {pairs}"
        )

        # request.form (attribute variable) should flow into the .get() call
        form_text = req_to_form[0][1]
        form_to_get = [(s, t) for s, t in pairs if s == form_text and "get" in t]
        assert form_to_get, (
            f"Expected {form_text!r} -> '.get()', got DATA_FLOWS_TO pairs: {pairs}"
        )

    def test_triple_chained_attribute(self):
        """a.b.c should chain: a -> a.b -> a.b.c."""
        source = b"""
def process(obj):
    val = obj.first.second
    return val
"""
        cpg = CPGBuilder().add_source(source, "triple_attr.py").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)

        # obj -> obj.first
        obj_to_first = [(s, t) for s, t in pairs if s == "obj" and "first" in t]
        assert obj_to_first, (
            f"Expected 'obj' -> 'obj.first', got pairs: {pairs}"
        )

        # obj.first -> obj.first.second
        first_text = obj_to_first[0][1]
        first_to_second = [(s, t) for s, t in pairs if s == first_text and "second" in t]
        assert first_to_second, (
            f"Expected {first_text!r} -> 'obj.first.second', got pairs: {pairs}"
        )


class TestFieldSensitivity:
    """Issue #52: obj.safe_field and obj.unsafe_field should be separate VARIABLE nodes."""

    def test_separate_variable_nodes_for_different_fields(self):
        """Two different fields on the same object should produce separate VARIABLE nodes."""
        source = b"""
def process(obj):
    x = obj.safe_field
    y = obj.unsafe_field
    return x, y
"""
        cpg = CPGBuilder().add_source(source, "field_sens.py").build()
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "obj.safe_field" in var_names or any("safe_field" in n for n in var_names), (
            f"Expected a variable for obj.safe_field, got: {var_names}"
        )
        assert "obj.unsafe_field" in var_names or any("unsafe_field" in n for n in var_names), (
            f"Expected a variable for obj.unsafe_field, got: {var_names}"
        )
        # The two field nodes must be distinct
        safe_nodes = [n for n in cpg.nodes(kind=NodeKind.VARIABLE) if "safe_field" in n.name]
        unsafe_nodes = [n for n in cpg.nodes(kind=NodeKind.VARIABLE) if "unsafe_field" in n.name]
        assert safe_nodes and unsafe_nodes
        assert safe_nodes[0].id != unsafe_nodes[0].id, (
            "safe_field and unsafe_field should be separate VARIABLE nodes"
        )

    def test_separate_dfg_chains_per_field(self):
        """Taint on obj.unsafe_field must not reach obj.safe_field."""
        source = b"""
def process(obj):
    x = obj.safe_field
    y = obj.unsafe_field
    return x, y
"""
        cpg = CPGBuilder().add_source(source, "field_taint.py").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)

        # There should be no edge from a safe_field node to an unsafe_field node
        # or vice versa — they are separate chains.
        cross_field = [
            (s, t) for s, t in pairs
            if ("safe_field" in s and "unsafe_field" in t)
            or ("unsafe_field" in s and "safe_field" in t)
        ]
        assert not cross_field, (
            f"safe_field and unsafe_field should not share data flow, got: {cross_field}"
        )

    def test_attribute_dfg_edges_carry_field_name(self):
        """DATA_FLOWS_TO edges from attribute access must carry a field_name attr."""
        source = b"""
def handle(request):
    form_data = request.form
    headers = request.headers
    return form_data
"""
        cpg = CPGBuilder().add_source(source, "attr_field_name.py").build()

        # request is a PARAMETER node; find it so we can check its outgoing edges.
        req_node = next(
            (n for n in cpg.nodes(kind=NodeKind.PARAMETER) if n.name == "request"),
            None,
        )
        assert req_node is not None, "Expected a 'request' PARAMETER node"

        dfg_edges = [
            e for e in cpg.edges(kind=EdgeKind.DATA_FLOWS_TO)
            if e.source == req_node.id
        ]
        assert dfg_edges, "Expected DATA_FLOWS_TO edges from 'request'"

        for edge in dfg_edges:
            assert "field_name" in edge.attrs, (
                f"Edge {edge.source} -> {edge.target} missing 'field_name' attr; "
                f"attrs={edge.attrs}"
            )

        field_names = {e.attrs["field_name"] for e in dfg_edges}
        assert "form" in field_names, f"Expected 'form' in field_names, got {field_names}"
        assert "headers" in field_names, f"Expected 'headers' in field_names, got {field_names}"


class TestTypeInference:
    """Type-based call resolution via constructor inference and MRO traversal."""

    @pytest.fixture()
    def cpg(self):
        return _build("type_inference.py")

    def test_class_bases_recorded(self, cpg):
        """Dog(Animal) should record bases=['Animal'] in attrs."""
        dog = next(n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Dog")
        assert dog.attrs.get("bases") == ["Animal"]

    def test_class_no_bases(self, cpg):
        """Animal has no bases, so attrs should have no 'bases' key."""
        animal = next(
            n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Animal"
        )
        assert "bases" not in animal.attrs

    def test_variable_inferred_type(self, cpg):
        """d = Dog() should set inferred_type='Dog' on the variable."""
        d_vars = [n for n in cpg.nodes(kind=NodeKind.VARIABLE) if n.name == "d"]
        assert len(d_vars) >= 1
        assert any(v.attrs.get("inferred_type") == "Dog" for v in d_vars)

    def test_call_receiver_type(self, cpg):
        """d.speak() should have receiver_inferred_type='Dog' in attrs."""
        speak_calls = [
            n for n in cpg.nodes(kind=NodeKind.CALL) if n.name == "d.speak"
        ]
        assert len(speak_calls) >= 1
        assert speak_calls[0].attrs.get("receiver_inferred_type") == "Dog"

    def test_dog_speak_resolves_to_dog_method(self, cpg):
        """d.speak() should resolve to Dog.speak, not Animal.speak."""
        dog_class = next(
            n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Dog"
        )
        dog_speak = next(
            n for n in cpg.nodes(kind=NodeKind.FUNCTION)
            if n.name == "speak" and n.scope == dog_class.id
        )
        d_speak_call = next(
            n for n in cpg.nodes(kind=NodeKind.CALL) if n.name == "d.speak"
        )
        calls_edges = list(cpg.edges(kind=EdgeKind.CALLS))
        assert any(
            e.source == d_speak_call.id and e.target == dog_speak.id
            for e in calls_edges
        ), (
            f"Expected d.speak() -> Dog.speak edge, got CALLS edges: "
            f"{[(cpg.node(e.source).name, cpg.node(e.target).name) for e in calls_edges]}"
        )

    def test_cat_speak_resolves_to_cat_method(self, cpg):
        """c.speak() should resolve to Cat.speak, not Animal.speak."""
        cat_class = next(
            n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Cat"
        )
        cat_speak = next(
            n for n in cpg.nodes(kind=NodeKind.FUNCTION)
            if n.name == "speak" and n.scope == cat_class.id
        )
        c_speak_call = next(
            n for n in cpg.nodes(kind=NodeKind.CALL) if n.name == "c.speak"
        )
        calls_edges = list(cpg.edges(kind=EdgeKind.CALLS))
        assert any(
            e.source == c_speak_call.id and e.target == cat_speak.id
            for e in calls_edges
        ), (
            f"Expected c.speak() -> Cat.speak edge, got CALLS edges: "
            f"{[(cpg.node(e.source).name, cpg.node(e.target).name) for e in calls_edges]}"
        )

    def test_inherited_method_resolves_via_mro(self, cpg):
        """d.breathe() should resolve to Animal.breathe (inherited)."""
        animal_class = next(
            n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Animal"
        )
        animal_breathe = next(
            n for n in cpg.nodes(kind=NodeKind.FUNCTION)
            if n.name == "breathe" and n.scope == animal_class.id
        )
        d_breathe_call = next(
            n for n in cpg.nodes(kind=NodeKind.CALL)
            if n.name == "d.breathe"
        )
        calls_edges = list(cpg.edges(kind=EdgeKind.CALLS))
        assert any(
            e.source == d_breathe_call.id and e.target == animal_breathe.id
            for e in calls_edges
        ), (
            f"Expected d.breathe() -> Animal.breathe edge, got CALLS edges: "
            f"{[(cpg.node(e.source).name, cpg.node(e.target).name) for e in calls_edges]}"
        )

    def test_own_method_resolves_directly(self, cpg):
        """d.fetch() should resolve to Dog.fetch (own method)."""
        dog_class = next(
            n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Dog"
        )
        dog_fetch = next(
            n for n in cpg.nodes(kind=NodeKind.FUNCTION)
            if n.name == "fetch" and n.scope == dog_class.id
        )
        d_fetch_call = next(
            n for n in cpg.nodes(kind=NodeKind.CALL) if n.name == "d.fetch"
        )
        calls_edges = list(cpg.edges(kind=EdgeKind.CALLS))
        assert any(
            e.source == d_fetch_call.id and e.target == dog_fetch.id
            for e in calls_edges
        ), (
            f"Expected d.fetch() -> Dog.fetch edge, got CALLS edges: "
            f"{[(cpg.node(e.source).name, cpg.node(e.target).name) for e in calls_edges]}"
        )


class TestSelfClsResolution:
    """self.method() and cls.method() should resolve via enclosing class."""

    @pytest.fixture()
    def cpg(self):
        return _build("self_method_calls.py")

    def test_self_calls_have_receiver_type(self, cpg):
        """self.method() calls should have receiver_inferred_type set."""
        self_calls = [
            n for n in cpg.nodes(kind=NodeKind.CALL)
            if n.name.startswith("self.")
        ]
        assert len(self_calls) > 0, "Expected self.method() call nodes"
        # All self calls inside Calculator should have receiver type
        for call in self_calls:
            assert call.attrs.get("receiver_inferred_type") is not None, (
                f"self call {call.name} at {call.location} missing receiver_inferred_type"
            )

    def test_self_reset_resolves_to_calculator_reset(self, cpg):
        """self.reset() in Calculator.compute should resolve to Calculator.reset."""
        calc_class = next(
            n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Calculator"
        )
        calc_reset = next(
            n for n in cpg.nodes(kind=NodeKind.FUNCTION)
            if n.name == "reset" and n.scope == calc_class.id
        )
        calls_edges = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("self.reset", "reset") in calls_edges, (
            f"Expected self.reset -> reset edge, got: {calls_edges}"
        )
        # Verify it's specifically Calculator.reset, not some other reset
        calls = list(cpg.edges(kind=EdgeKind.CALLS))
        reset_calls = [
            e for e in calls
            if cpg.node(e.source) and cpg.node(e.source).name == "self.reset"
        ]
        assert any(e.target == calc_reset.id for e in reset_calls)

    def test_self_add_resolves_in_subclass(self, cpg):
        """self.add() in AdvancedCalc.compute should resolve to Calculator.add (inherited)."""
        calc_class = next(
            n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Calculator"
        )
        calc_add = next(
            n for n in cpg.nodes(kind=NodeKind.FUNCTION)
            if n.name == "add" and n.scope == calc_class.id
        )
        # AdvancedCalc.compute calls self.add() — AdvancedCalc inherits add from Calculator
        adv_class = next(
            n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "AdvancedCalc"
        )
        # Find self.add calls inside AdvancedCalc scope (inside compute)
        adv_compute = next(
            n for n in cpg.nodes(kind=NodeKind.FUNCTION)
            if n.name == "compute" and n.scope == adv_class.id
        )
        adv_add_calls = [
            n for n in cpg.nodes(kind=NodeKind.CALL)
            if n.name == "self.add" and n.scope == adv_compute.id
        ]
        assert len(adv_add_calls) >= 1, "Expected self.add() call inside AdvancedCalc.compute"
        calls_edges = list(cpg.edges(kind=EdgeKind.CALLS))
        assert any(
            e.source == adv_add_calls[0].id and e.target == calc_add.id
            for e in calls_edges
        ), (
            f"Expected self.add() in AdvancedCalc -> Calculator.add, got CALLS: "
            f"{[(cpg.node(e.source).name, cpg.node(e.target).name) for e in calls_edges]}"
        )

    def test_self_multiply_resolves_to_own_method(self, cpg):
        """self.multiply() in AdvancedCalc.compute should resolve to AdvancedCalc.multiply."""
        adv_class = next(
            n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "AdvancedCalc"
        )
        adv_multiply = next(
            n for n in cpg.nodes(kind=NodeKind.FUNCTION)
            if n.name == "multiply" and n.scope == adv_class.id
        )
        multiply_calls = [
            n for n in cpg.nodes(kind=NodeKind.CALL)
            if n.name == "self.multiply"
        ]
        assert len(multiply_calls) >= 1
        calls_edges = list(cpg.edges(kind=EdgeKind.CALLS))
        assert any(
            e.source == multiply_calls[0].id and e.target == adv_multiply.id
            for e in calls_edges
        )


class TestImportFollowingResolution:
    """Calls to imported functions should resolve when the source module is in the CPG."""

    @pytest.fixture()
    def cpg(self):
        builder = CPGBuilder()
        builder.add_file(FIXTURES / "import_resolution_lib.py")
        builder.add_file(FIXTURES / "import_resolution_caller.py")
        return builder.build()

    def test_helper_call_resolves(self, cpg):
        """helper() in caller should resolve to helper() in lib."""
        calls_edges = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("helper", "helper") in calls_edges, (
            f"Expected helper -> helper edge, got: {calls_edges}"
        )

    def test_transform_call_resolves(self, cpg):
        """transform() in caller should resolve to transform() in lib."""
        calls_edges = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("transform", "transform") in calls_edges, (
            f"Expected transform -> transform edge, got: {calls_edges}"
        )

    def test_resolved_targets_are_in_lib_module(self, cpg):
        """Resolved functions should be scoped inside the lib module, not the caller."""
        lib_module = next(
            n for n in cpg.nodes(kind=NodeKind.MODULE)
            if n.name == "import_resolution_lib"
        )
        calls = list(cpg.edges(kind=EdgeKind.CALLS))
        for edge in calls:
            target = cpg.node(edge.target)
            if target and target.name in ("helper", "transform"):
                assert target.scope == lib_module.id, (
                    f"{target.name} should be scoped in import_resolution_lib, "
                    f"got scope {cpg.scope_of(target.id).name if cpg.scope_of(target.id) else '?'}"
                )


class TestEndLocation:
    """Verify the Python visitor populates end_location on all node kinds."""

    @pytest.fixture()
    def cpg(self):
        return _build("simple_function.py")

    def test_module_has_end_location(self, cpg):
        mod = next(cpg.nodes(kind=NodeKind.MODULE))
        assert mod.end_location is not None
        assert mod.end_location.line >= mod.location.line

    def test_function_has_end_location(self, cpg):
        func = next(n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "add")
        assert func.end_location is not None
        assert func.end_location.line >= func.location.line

    def test_parameter_has_end_location(self, cpg):
        params = list(cpg.nodes(kind=NodeKind.PARAMETER))
        assert len(params) > 0
        for p in params:
            assert p.end_location is not None, f"Parameter {p.name!r} missing end_location"

    def test_end_location_after_start(self, cpg):
        """end_location should always be at or after location (start)."""
        for node in cpg.nodes():
            if node.location is not None and node.end_location is not None:
                assert (node.end_location.line, node.end_location.column) >= (
                    node.location.line, node.location.column
                ), f"Node {node.name!r} has end before start"


class TestSourceText:
    """Verify include_source mode populates source_text on indexable nodes."""

    @pytest.fixture()
    def cpg_with_source(self):
        return (
            CPGBuilder(include_source=True)
            .add_file(FIXTURES / "simple_function.py")
            .build()
        )

    @pytest.fixture()
    def cpg_without_source(self):
        return _build("simple_function.py")

    def test_function_has_source_text(self, cpg_with_source):
        func = next(
            n for n in cpg_with_source.nodes(kind=NodeKind.FUNCTION)
            if n.name == "add"
        )
        assert "source_text" in func.attrs
        assert "def add" in func.attrs["source_text"]

    def test_module_no_source_text(self, cpg_with_source):
        """Module nodes skip source_text (it would be the entire file)."""
        mod = next(cpg_with_source.nodes(kind=NodeKind.MODULE))
        assert "source_text" not in mod.attrs

    def test_default_no_source_text(self, cpg_without_source):
        """Without include_source, no node should have source_text in attrs."""
        for node in cpg_without_source.nodes():
            assert "source_text" not in node.attrs, (
                f"Node {node.name!r} has source_text without include_source"
            )


class TestCoverageEdgeCases:
    """Tests targeting specific uncovered lines in python.py."""

    # -- Import-following with aliased from-import (lines 142-152) --------

    def test_import_following_resolves_aliased_from_import(self):
        """from pkg.utils import helper as h; h() should resolve to helper()
        when both modules are in the CPG."""
        lib_src = b"""
def helper(data):
    return data.strip()
"""
        caller_src = b"""
from pkg.utils import helper as h

def process(raw):
    return h(raw)
"""
        cpg = (
            CPGBuilder()
            .add_source(lib_src, "utils.py", "python")
            .add_source(caller_src, "caller.py", "python")
            .build()
        )
        calls_edges = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("h", "helper") in calls_edges, (
            f"Expected h -> helper via import-following, got: {calls_edges}"
        )

    # -- MRO cycle detection (line 173) -----------------------------------

    def test_mro_cycle_does_not_infinite_loop(self):
        """When MRO encounters a cycle (A->B->A), the visited-set guard
        must prevent infinite looping.  Exercise by looking up a method
        that does NOT exist so the walk exhausts the entire cycle."""
        source = b"""
class A(B):
    def method(self):
        return 1

class B(A):
    pass

def main():
    a = A()
    a.nonexistent()
"""
        cpg = CPGBuilder().add_source(source, "cycle.py", "python").build()
        # a.nonexistent() should not resolve (no such method anywhere)
        # and the build should complete without hanging
        calls_edges = _edge_pairs(cpg, EdgeKind.CALLS)
        nonexistent_resolved = [
            (s, t) for s, t in calls_edges if "nonexistent" in s
        ]
        assert not nonexistent_resolved, (
            "nonexistent() should not resolve in a cyclic hierarchy"
        )

    # -- Direct scope match for qualified calls (line 209) ----------------

    def test_qualified_call_direct_scope_match(self):
        """Worker.work(w) with multiple 'work' functions should resolve to
        the one directly scoped in Worker (line 209)."""
        source = b"""
class Worker:
    def work(self):
        return 1

def work():
    return 2

def main():
    w = Worker()
    Worker.work(w)
"""
        cpg = CPGBuilder().add_source(source, "direct_scope.py", "python").build()
        calls_edges = _edge_pairs(cpg, EdgeKind.CALLS)
        resolved = [(s, t) for s, t in calls_edges if "Worker.work" in s]
        assert resolved, f"Expected Worker.work() to be resolved, got: {calls_edges}"

    # -- Multi-level scope disambiguation (lines 211-216) -----------------

    def test_qualified_call_multilevel_scope_walk(self):
        """Outer.helper() where helper is in Inner (nested in Outer) should
        resolve by walking up the scope chain: Inner -> Outer (match)."""
        source = b"""
class Outer:
    class Inner:
        def helper(self):
            return 1

def helper():
    return 2

def main():
    o = Outer.Inner()
    Outer.helper(o)
"""
        cpg = CPGBuilder().add_source(source, "nested_scope.py", "python").build()
        calls_edges = _edge_pairs(cpg, EdgeKind.CALLS)
        resolved = [(s, t) for s, t in calls_edges if "Outer.helper" in s]
        assert resolved, f"Expected Outer.helper() to be resolved, got: {calls_edges}"
        # Should resolve to Inner's helper (found by walking scope up to Outer)
        target_scopes = []
        for e in cpg.edges(kind=EdgeKind.CALLS):
            src = cpg.node(e.source)
            tgt = cpg.node(e.target)
            if src and tgt and "Outer.helper" in src.name:
                scope = cpg.scope_of(tgt.id)
                target_scopes.append(scope.name if scope else None)
        assert "Inner" in target_scopes, (
            f"Expected helper in Inner scope, got: {target_scopes}"
        )

    # -- Dotted base class name (line 254) --------------------------------

    def test_dotted_base_class_name(self):
        """class Foo(module.Base) should record the dotted name in bases."""
        source = b"""
class Foo(module.Base):
    def method(self):
        return 1
"""
        cpg = CPGBuilder().add_source(source, "dotted_base.py", "python").build()
        foo = next(n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Foo")
        bases = foo.attrs.get("bases", [])
        assert "module.Base" in bases, (
            f"Expected dotted base class name 'module.Base', got bases={bases}"
        )

    # -- Aliased from-import (lines 498-504) ------------------------------

    def test_from_import_aliased_name(self):
        """from module import X as Y should record aliases={X: Y}."""
        source = b"""
from collections import OrderedDict as OD
"""
        cpg = CPGBuilder().add_source(source, "aliased_from.py", "python").build()
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) == 1
        imp = imports[0]
        assert imp.attrs.get("is_from") is True
        assert imp.attrs.get("module") == "collections"
        assert "OrderedDict" in imp.attrs.get("names", [])
        assert imp.attrs.get("aliases") == {"OrderedDict": "OD"}

    # -- Subscript with attribute/subscript receiver (lines 749-752) ------

    def test_subscript_on_attribute_receiver(self):
        """obj.items[0] should wire data flow from obj.items to the subscript."""
        source = b"""
def process(obj):
    x = obj.items[0]
    return x
"""
        cpg = CPGBuilder().add_source(source, "sub_attr.py", "python").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        attr_to_sub = [
            (s, t) for s, t in pairs if "items" in s and "[" in t
        ]
        assert attr_to_sub, (
            f"Expected obj.items -> obj.items[0] data flow, got: {pairs}"
        )

    def test_nested_subscript_receiver(self):
        """data['a']['b'] should wire data flow from the outer subscript."""
        source = b"""
def get(data):
    x = data['a']['b']
    return x
"""
        cpg = CPGBuilder().add_source(source, "nested_sub.py", "python").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        data_to_inner = [(s, t) for s, t in pairs if s == "data" and "[" in t]
        assert data_to_inner, (
            f"Expected data -> data['a'] flow, got: {pairs}"
        )

    # -- Percent formatting (lines 764-795) -------------------------------

    def test_percent_format_detected(self):
        """'%s' % var should create a % pseudo-call node with data flow."""
        source = b"""
def fmt(val):
    result = "hello %s" % val
    return result
"""
        cpg = CPGBuilder().add_source(source, "pct_fmt.py", "python").build()
        calls = _node_names(cpg, NodeKind.CALL)
        assert "%" in calls, (
            f"Expected % pseudo-call node, got calls: {calls}"
        )
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        val_to_pct = [(s, t) for s, t in pairs if s == "val" and t == "%"]
        assert val_to_pct, (
            f"Expected 'val' -> '%' data flow, got: {pairs}"
        )

    # -- Parenthesized expression (lines 810-812) -------------------------

    def test_parenthesized_expression_propagates(self):
        """x = (a) should propagate data flow through parenthesized expr."""
        source = b"""
def compute(a, b):
    x = (a)
    return x
"""
        cpg = CPGBuilder().add_source(source, "paren_expr.py", "python").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        a_to_x = [(s, t) for s, t in pairs if s == "a" and t == "x"]
        assert a_to_x, (
            f"Expected 'a' -> 'x' via parenthesized expression, got: {pairs}"
        )

    # -- Keyword argument data flow (line 815-820) ------------------------

    def test_keyword_arg_flows_to_call(self):
        """func(key=val) where val is a known variable should flow to the call."""
        source = b"""
def run(data):
    result = process(key=data)
    return result
"""
        cpg = CPGBuilder().add_source(source, "kw_flow.py", "python").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        data_to_call = [(s, t) for s, t in pairs if s == "data" and t == "process"]
        assert data_to_call, (
            f"Expected 'data' -> 'process' via keyword arg, got: {pairs}"
        )

    # -- Dictionary splat data flow (lines 823-828) -----------------------

    def test_dict_splat_unknown_var(self):
        """func(**unknown_var) where unknown_var is not in defined_vars
        should not crash."""
        source = b"""
def run():
    process(**unknown_var)
"""
        cpg = CPGBuilder().add_source(source, "splat_unknown.py", "python").build()
        calls = _node_names(cpg, NodeKind.CALL)
        assert "process" in calls

    # -- Dictionary comprehension (lines 850-859) -------------------------

    def test_dict_comprehension(self):
        """Calls inside dict comprehension iterables should be visited."""
        source = b"""
def transform(items):
    result = {k: v for k, v in get_pairs(items)}
    return result
"""
        cpg = CPGBuilder().add_source(source, "dict_comp.py", "python").build()
        calls = _node_names(cpg, NodeKind.CALL)
        assert "get_pairs" in calls, (
            f"Expected get_pairs() inside dict comprehension, got: {calls}"
        )

    # -- Parameter extraction for typed/splat/default params (1085-1109) --

    @pytest.mark.parametrize(
        "signature,expected_params",
        [
            ("def f(x: int, y: str): pass", {"x", "y"}),
            ("def f(*args): pass", {"*args"}),
            ("def f(**kwargs): pass", {"**kwargs"}),
            ("def f(x=5, y='hi'): pass", {"x", "y"}),
            ("def f(a, *args, **kwargs): pass", {"a", "*args", "**kwargs"}),
        ],
        ids=["typed", "splat", "dict_splat", "default", "mixed"],
    )
    def test_param_extraction_variants(self, signature, expected_params):
        """Various parameter syntaxes should all be extracted correctly."""
        source = signature.encode()
        cpg = CPGBuilder().add_source(source, "params.py", "python").build()
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert param_names == expected_params, (
            f"Expected params {expected_params}, got {param_names}"
        )

    # -- Typed self parameter (line 1101: break in _extract_single_param_name) --

    def test_typed_self_parameter_excluded(self):
        """def method(self: ClassName, x: int) should exclude typed self."""
        source = b"""
class MyClass:
    def method(self: MyClass, x: int):
        pass
"""
        cpg = CPGBuilder().add_source(source, "typed_self.py", "python").build()
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "self" not in param_names
        assert "x" in param_names

    # -- async function detection ------------------------------------------

    def test_async_function_detected(self) -> None:
        """async def should set is_async=True on the FUNCTION node."""
        src = b"""
async def fetch(url):
    return url
"""
        cpg = CPGBuilder().add_source(src, "test.py", "python").build()
        func = next(n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "fetch")
        assert func.attrs.get("is_async") is True

    def test_sync_function_not_async(self) -> None:
        src = b"""
def compute(x):
    return x
"""
        cpg = CPGBuilder().add_source(src, "test.py", "python").build()
        func = next(n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "compute")
        assert func.attrs.get("is_async") is not True
