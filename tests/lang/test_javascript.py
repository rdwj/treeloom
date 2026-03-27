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


# Use the same FIXTURE_DIR alias as the helper constant above
FIXTURE_DIR = FIXTURES


class TestDataFlow:
    """Data flow chain tests for JavaScript."""

    @pytest.fixture()
    def cpg(self):
        return _build("data_flow.js")

    def test_functions_emitted(self, cpg):
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert "transform" in func_names
        assert "multiAssign" in func_names

    def test_assignment_chain_variables(self, cpg):
        """Variables in assignment chain are emitted."""
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "x" in var_names
        assert "y" in var_names
        assert "result" in var_names

    def test_data_flow_edges_exist(self, cpg):
        """DATA_FLOWS_TO edges connect assignment chain."""
        dfg_edges = list(cpg.edges(kind=EdgeKind.DATA_FLOWS_TO))
        assert len(dfg_edges) > 0

    def test_assignment_chain_x_to_y(self, cpg):
        """x flows to y (let y = x)."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("x", "y") in pairs

    def test_variable_to_return_flow(self, cpg):
        """y flows to return in transform; result flows to return in multiAssign."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("y", "return") in pairs
        assert ("result", "return") in pairs

    def test_param_nodes_emitted(self, cpg):
        """Parameters for both functions are present."""
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "input" in param_names
        assert "a" in param_names
        assert "b" in param_names

    def test_module_level_variables(self, cpg):
        """Module-level const declarations are emitted."""
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "value" in var_names
        assert "output" in var_names

    def test_call_to_variable_flow(self, cpg):
        """Call result flows into the module-level variable (value = transform(...))."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("transform", "value") in pairs
        assert ("multiAssign", "output") in pairs


class TestCrossFunctionTaint:
    """Cross-function taint propagation tests."""

    @pytest.fixture()
    def cpg(self):
        return _build("cross_function_taint.js")

    def test_functions_exist(self, cpg):
        """All four functions are discovered."""
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert {"source", "passthrough", "sink", "main"}.issubset(func_names)

    def test_call_nodes_exist(self, cpg):
        """Call sites for source(), passthrough(), sink() are emitted."""
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "source" in call_names
        assert "passthrough" in call_names
        assert "sink" in call_names

    def test_call_resolution(self, cpg):
        """Calls resolve to their target functions via CALLS edges."""
        calls_edges = list(cpg.edges(kind=EdgeKind.CALLS))
        assert len(calls_edges) >= 1
        # Every resolved target should be a known function node
        func_ids = {str(n.id) for n in cpg.nodes(kind=NodeKind.FUNCTION)}
        resolved_targets = {str(e.target) for e in calls_edges}
        assert resolved_targets & func_ids  # at least one overlap

    def test_main_variables(self, cpg):
        """data and processed are emitted as variables inside main."""
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "data" in var_names
        assert "processed" in var_names

    def test_source_call_to_data_flow(self, cpg):
        """Return value of source() flows into 'data'."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("source", "data") in pairs

    def test_passthrough_call_to_processed(self, cpg):
        """Return value of passthrough() flows into 'processed'."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("passthrough", "processed") in pairs

    def test_arg_flows_to_call(self, cpg):
        """'processed' flows into the sink() call as an argument."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("processed", "sink") in pairs


class TestMethodCalls:
    """Method call and class interaction tests."""

    @pytest.fixture()
    def cpg(self):
        return _build("method_calls.js")

    def test_class_exists(self, cpg):
        classes = [n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Processor"]
        assert len(classes) == 1

    def test_methods_exist(self, cpg):
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert "constructor" in func_names
        assert "process" in func_names
        assert "validate" in func_names

    def test_methods_scoped_to_class(self, cpg):
        """constructor, process, and validate should be contained in Processor."""
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("Processor", "constructor") in pairs
        assert ("Processor", "process") in pairs
        assert ("Processor", "validate") in pairs

    def test_method_calls_emitted(self, cpg):
        """p.process() and p.validate() calls are emitted."""
        call_names = _node_names(cpg, NodeKind.CALL)
        assert "p.process" in call_names
        assert "p.validate" in call_names

    def test_method_calls_resolve_to_methods(self, cpg):
        """p.process resolves to the process method; p.validate to validate."""
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("p.process", "process") in pairs
        assert ("p.validate", "validate") in pairs

    def test_result_flows_to_return(self, cpg):
        """'valid' flows to the return node in run()."""
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("valid", "return") in pairs

    def test_run_function_exists(self, cpg):
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert "run" in func_names


class TestNestedScopes:
    """Nested function scope tests."""

    @pytest.fixture()
    def cpg(self):
        return _build("nested_scopes.js")

    def test_outer_and_inner_functions(self, cpg):
        func_names = _node_names(cpg, NodeKind.FUNCTION)
        assert "outer" in func_names
        assert "inner" in func_names

    def test_outer_params(self, cpg):
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "x" in param_names

    def test_inner_params(self, cpg):
        param_names = _node_names(cpg, NodeKind.PARAMETER)
        assert "y" in param_names

    def test_inner_scoped_inside_outer(self, cpg):
        """inner function's scope should be the outer function node."""
        outer_nodes = [n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "outer"]
        inner_nodes = [n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "inner"]
        assert len(outer_nodes) >= 1
        assert len(inner_nodes) >= 1
        assert inner_nodes[0].scope is not None
        assert inner_nodes[0].scope == outer_nodes[0].id

    def test_inner_call_resolves(self, cpg):
        """inner(10) call resolves to the inner function definition."""
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("inner", "inner") in pairs

    def test_closure_variable_emitted(self, cpg):
        """Module-level 'closure' const is emitted as a variable."""
        var_names = _node_names(cpg, NodeKind.VARIABLE)
        assert "closure" in var_names
