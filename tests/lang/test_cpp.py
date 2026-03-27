"""Tests for the C++ language visitor.

Uses CPGBuilder to parse fixture files and asserts on the resulting graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.builder import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "cpp"


def _build(fixture_name: str) -> CodePropertyGraph:
    return CPGBuilder().add_file(FIXTURES / fixture_name).build()


def _names(cpg: CodePropertyGraph, kind: NodeKind) -> set[str]:
    return {n.name for n in cpg.nodes(kind=kind)}


def _edge_pairs(cpg: CodePropertyGraph, kind: EdgeKind) -> list[tuple[str, str]]:
    pairs = []
    for e in cpg.edges(kind=kind):
        src = cpg.node(e.source)
        tgt = cpg.node(e.target)
        if src and tgt:
            pairs.append((src.name, tgt.name))
    return pairs


class TestSimpleClass:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("simple_class.cpp")

    def test_module_node(self, cpg: CodePropertyGraph) -> None:
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "simple_class"

    def test_class_nodes(self, cpg: CodePropertyGraph) -> None:
        class_names = _names(cpg, NodeKind.CLASS)
        assert "Animal" in class_names
        assert "Dog" in class_names

    def test_class_contained_in_module(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("simple_class", "Animal") in pairs
        assert ("simple_class", "Dog") in pairs

    def test_methods_emitted(self, cpg: CodePropertyGraph) -> None:
        func_names = _names(cpg, NodeKind.FUNCTION)
        assert "Animal" in func_names      # constructor
        assert "getName" in func_names
        assert "getAge" in func_names
        assert "setAge" in func_names
        assert "Dog" in func_names         # Dog constructor
        assert "speak" in func_names

    def test_methods_scoped_to_class(self, cpg: CodePropertyGraph) -> None:
        for fn in cpg.nodes(kind=NodeKind.FUNCTION):
            scope = cpg.scope_of(fn.id)
            assert scope is not None, f"{fn.name!r} has no scope"
            assert scope.kind == NodeKind.CLASS

    def test_constructor_params(self, cpg: CodePropertyGraph) -> None:
        params = {n.name: n for n in cpg.nodes(kind=NodeKind.PARAMETER)}
        assert "name" in params
        assert "age" in params

    def test_has_parameter_edges(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.HAS_PARAMETER)
        # Animal constructor has name and age parameters
        assert ("Animal", "name") in pairs
        assert ("Animal", "age") in pairs
        assert ("setAge", "age") in pairs

    def test_member_variables(self, cpg: CodePropertyGraph) -> None:
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "name_" in var_names
        assert "age_" in var_names

    def test_return_node(self, cpg: CodePropertyGraph) -> None:
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(returns) >= 2  # getName and getAge both return

    def test_data_flow_to_return(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # greeting flows to return in speak()
        assert ("greeting", "return") in pairs

    def test_include_import(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) >= 1
        modules = {i.attrs.get("module") for i in imports}
        assert "string" in modules


class TestFunctions:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("functions.cpp")

    def test_module_node(self, cpg: CodePropertyGraph) -> None:
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "functions"

    def test_function_nodes(self, cpg: CodePropertyGraph) -> None:
        func_names = _names(cpg, NodeKind.FUNCTION)
        assert "add" in func_names
        assert "multiply" in func_names
        assert "greet" in func_names
        assert "main" in func_names

    def test_template_function(self, cpg: CodePropertyGraph) -> None:
        # Template function should also be emitted
        func_names = _names(cpg, NodeKind.FUNCTION)
        assert "max_val" in func_names

    def test_parameters_with_types(self, cpg: CodePropertyGraph) -> None:
        # Collect all parameters; there may be multiple "a" (e.g. add and max_val).
        # Find the one scoped to "add" with type "int".
        all_params = list(cpg.nodes(kind=NodeKind.PARAMETER))
        add_params = [
            p for p in all_params
            if cpg.scope_of(p.id) is not None
            and cpg.scope_of(p.id).name == "add"  # type: ignore[union-attr]
        ]
        assert any(p.name == "a" and p.attrs.get("type_annotation") == "int" for p in add_params)
        assert any(p.name == "b" and p.attrs.get("type_annotation") == "int" for p in add_params)
        a_param = next(p for p in add_params if p.name == "a")
        b_param = next(p for p in add_params if p.name == "b")
        assert a_param.attrs["position"] == 0
        assert b_param.attrs["position"] == 1

    def test_has_parameter_edges(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.HAS_PARAMETER)
        assert ("add", "a") in pairs
        assert ("add", "b") in pairs
        assert ("multiply", "x") in pairs
        assert ("multiply", "y") in pairs

    def test_local_variables(self, cpg: CodePropertyGraph) -> None:
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "result" in var_names
        assert "msg" in var_names

    def test_call_nodes(self, cpg: CodePropertyGraph) -> None:
        call_names = _names(cpg, NodeKind.CALL)
        assert "add" in call_names
        assert "multiply" in call_names
        assert "greet" in call_names

    def test_call_resolution(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("add", "add") in pairs
        assert ("multiply", "multiply") in pairs
        assert ("greet", "greet") in pairs

    def test_data_flow_result_to_return(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in pairs

    def test_data_flow_var_to_call(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # sum = add(3,4); product = multiply(sum, 2) => sum flows into multiply call
        assert ("sum", "multiply") in pairs

    def test_return_nodes(self, cpg: CodePropertyGraph) -> None:
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(returns) >= 3

    def test_include_import(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert any(i.attrs.get("module") == "string" for i in imports)


class TestControlFlow:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("control_flow.cpp")

    def test_function_nodes(self, cpg: CodePropertyGraph) -> None:
        func_names = _names(cpg, NodeKind.FUNCTION)
        assert "classify" in func_names
        assert "sumTo" in func_names
        assert "countdown" in func_names

    def test_branch_node_emitted(self, cpg: CodePropertyGraph) -> None:
        branches = list(cpg.nodes(kind=NodeKind.BRANCH))
        assert len(branches) >= 1
        branch_types = {b.attrs.get("branch_type") for b in branches}
        assert "if" in branch_types

    def test_if_has_else(self, cpg: CodePropertyGraph) -> None:
        if_branches = [
            b for b in cpg.nodes(kind=NodeKind.BRANCH)
            if b.attrs.get("branch_type") == "if"
        ]
        # classify() has if/else-if/else
        assert any(b.attrs.get("has_else") is True for b in if_branches)

    def test_for_loop_node(self, cpg: CodePropertyGraph) -> None:
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "for"
        ]
        assert len(loops) >= 1

    def test_for_loop_variable_emitted(self, cpg: CodePropertyGraph) -> None:
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "i" in var_names

    def test_while_loop_node(self, cpg: CodePropertyGraph) -> None:
        while_loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "while"
        ]
        assert len(while_loops) >= 1

    def test_local_variables(self, cpg: CodePropertyGraph) -> None:
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "total" in var_names

    def test_branch_contained_in_function(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("classify", "if") in pairs

    def test_loop_contained_in_function(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("sumTo", "for") in pairs
        assert ("countdown", "while") in pairs

    def test_data_flow_to_return(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("total", "return") in pairs

    def test_return_nodes(self, cpg: CodePropertyGraph) -> None:
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        # classify: 3 returns, sumTo: 1, countdown: 0, sumArray: 1, joinWords: 1
        assert len(returns) >= 4


class TestRangeBasedFor:
    """Verify range-based for loop handling via inline source."""

    def test_range_for_loop_node(self) -> None:
        src = b"""
#include <vector>
int main() {
    int total = 0;
    int arr[] = {1, 2, 3};
    for (auto item : arr) {
        total = total + item;
    }
    return total;
}
"""
        cpg = CPGBuilder().add_source(src, "range_for.cpp", "cpp").build()
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "for"
        ]
        assert len(loops) >= 1

    def test_range_for_iterator_var(self) -> None:
        src = b"""
int main() {
    int arr[] = {1, 2, 3};
    for (auto item : arr) {
        int x = item;
    }
    return 0;
}
"""
        cpg = CPGBuilder().add_source(src, "range_for2.cpp", "cpp").build()
        enhanced = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("iterator_var") is not None
        ]
        assert len(enhanced) >= 1
        assert enhanced[0].attrs["iterator_var"] == "item"

    def test_range_for_variable_emitted(self) -> None:
        src = b"""
int main() {
    int arr[] = {1, 2, 3};
    for (auto val : arr) {
        int y = val;
    }
    return 0;
}
"""
        cpg = CPGBuilder().add_source(src, "range_for3.cpp", "cpp").build()
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "val" in var_names


class TestImports:
    """Verify #include and using declarations produce IMPORT nodes."""

    def test_preproc_include(self) -> None:
        src = b"""
#include <iostream>
#include <string>
int main() { return 0; }
"""
        cpg = CPGBuilder().add_source(src, "inc.cpp", "cpp").build()
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) == 2
        modules = {i.attrs.get("module") for i in imports}
        assert "iostream" in modules
        assert "string" in modules

    def test_using_declaration(self) -> None:
        src = b"""
using namespace std;
int main() { return 0; }
"""
        cpg = CPGBuilder().add_source(src, "using.cpp", "cpp").build()
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) == 1
        assert imports[0].attrs.get("module") == "std"


class TestStructSpecifier:
    """Structs should be treated as CLASS nodes."""

    def test_struct_emitted_as_class(self) -> None:
        src = b"""
struct Point {
    int x;
    int y;
    int magnitude() {
        return x + y;
    }
};
int main() {
    return 0;
}
"""
        cpg = CPGBuilder().add_source(src, "point.cpp", "cpp").build()
        class_names = _names(cpg, NodeKind.CLASS)
        assert "Point" in class_names

    def test_struct_fields(self) -> None:
        src = b"""
struct Rect {
    int width;
    int height;
};
"""
        cpg = CPGBuilder().add_source(src, "rect.cpp", "cpp").build()
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "width" in var_names
        assert "height" in var_names


class TestCallResolution:
    """Verify call resolution handles C++ qualified names."""

    def test_simple_call_resolved(self) -> None:
        src = b"""
int helper(int x) { return x + 1; }
int main() {
    int result = helper(5);
    return result;
}
"""
        cpg = CPGBuilder().add_source(src, "calls.cpp", "cpp").build()
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("helper", "helper") in pairs

    def test_data_flow_arg_to_call(self) -> None:
        src = b"""
void process(int val) { }
int main() {
    int input = 42;
    process(input);
    return 0;
}
"""
        cpg = CPGBuilder().add_source(src, "dfcall.cpp", "cpp").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert any(src_name == "input" for src_name, _ in pairs)

    def test_method_call_emitted(self) -> None:
        src = b"""
class Foo {
public:
    int bar() { return 1; }
    void run() {
        int v = bar();
    }
};
"""
        cpg = CPGBuilder().add_source(src, "method.cpp", "cpp").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert "bar" in call_names


class TestRegistryIntegration:
    """Verify C++ visitor is accessible via the default registry."""

    def test_cpp_extensions_registered(self) -> None:
        from treeloom.lang.registry import LanguageRegistry

        registry = LanguageRegistry.default()
        for ext in (".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh"):
            visitor = registry.get_visitor(ext)
            assert visitor is not None, f"No visitor for {ext}"
            assert visitor.name == "cpp"

    def test_cpp_visitor_by_name(self) -> None:
        from treeloom.lang.registry import LanguageRegistry

        registry = LanguageRegistry.default()
        visitor = registry.get_visitor_by_name("cpp")
        assert visitor is not None

    def test_add_source_with_cpp_language(self) -> None:
        src = b"""
int add(int a, int b) { return a + b; }
"""
        cpg = CPGBuilder().add_source(src, "add.cpp", "cpp").build()
        assert "add" in _names(cpg, NodeKind.FUNCTION)


# ---------------------------------------------------------------------------
# data_flow.cpp
# ---------------------------------------------------------------------------


class TestDataFlow:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("data_flow.cpp")

    def test_module_node(self, cpg: CodePropertyGraph) -> None:
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "data_flow"

    def test_function_nodes(self, cpg: CodePropertyGraph) -> None:
        func_names = _names(cpg, NodeKind.FUNCTION)
        assert "transform" in func_names
        assert "multiAssign" in func_names

    def test_variable_nodes(self, cpg: CodePropertyGraph) -> None:
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "x" in var_names
        assert "y" in var_names
        assert "result" in var_names

    def test_return_nodes(self, cpg: CodePropertyGraph) -> None:
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(returns) == 2

    def test_dfg_chain_in_transform(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("x", "y") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"
        assert ("y", "return") in pairs

    def test_dfg_multi_assign(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("a", "result") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"
        assert ("b", "result") in pairs
        assert ("result", "return") in pairs

    def test_contains_variables_in_functions(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("transform", "x") in pairs
        assert ("transform", "y") in pairs
        assert ("multiAssign", "result") in pairs

    def test_include_import(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert any(i.attrs.get("module") == "string" for i in imports)


# ---------------------------------------------------------------------------
# cross_function_taint.cpp
# ---------------------------------------------------------------------------


class TestCrossFunctionTaint:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("cross_function_taint.cpp")

    def test_module_node(self, cpg: CodePropertyGraph) -> None:
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "cross_function_taint"

    def test_function_nodes(self, cpg: CodePropertyGraph) -> None:
        func_names = _names(cpg, NodeKind.FUNCTION)
        assert "source" in func_names
        assert "passthrough" in func_names
        assert "sink" in func_names
        assert "main" in func_names

    def test_call_nodes(self, cpg: CodePropertyGraph) -> None:
        call_names = _names(cpg, NodeKind.CALL)
        assert "source" in call_names
        assert "passthrough" in call_names
        assert "sink" in call_names

    def test_call_resolution(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("source", "source") in pairs, f"CALLS pairs: {pairs}"
        assert ("passthrough", "passthrough") in pairs
        assert ("sink", "sink") in pairs

    def test_variable_nodes(self, cpg: CodePropertyGraph) -> None:
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "data" in var_names
        assert "processed" in var_names

    def test_dfg_source_to_data(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("source", "data") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"

    def test_dfg_data_to_passthrough(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("data", "passthrough") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"

    def test_dfg_processed_to_sink(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("processed", "sink") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"

    def test_include_imports(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        modules = {i.attrs.get("module") for i in imports}
        assert "iostream" in modules
        assert "string" in modules


# ---------------------------------------------------------------------------
# method_calls.cpp
# ---------------------------------------------------------------------------


class TestMethodCalls:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("method_calls.cpp")

    def test_module_node(self, cpg: CodePropertyGraph) -> None:
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "method_calls"

    def test_class_node(self, cpg: CodePropertyGraph) -> None:
        class_names = _names(cpg, NodeKind.CLASS)
        assert "Processor" in class_names

    def test_method_nodes(self, cpg: CodePropertyGraph) -> None:
        func_names = _names(cpg, NodeKind.FUNCTION)
        assert "Processor" in func_names   # constructor
        assert "process" in func_names
        assert "validate" in func_names
        assert "run" in func_names

    def test_methods_scoped_to_class(self, cpg: CodePropertyGraph) -> None:
        # constructor and instance methods live inside the class
        class_methods = {"Processor", "process", "validate"}
        for fn in cpg.nodes(kind=NodeKind.FUNCTION):
            if fn.name in class_methods:
                scope = cpg.scope_of(fn.id)
                assert scope is not None, f"{fn.name!r} has no scope"
                assert scope.kind == NodeKind.CLASS, f"{fn.name!r} scoped to {scope.kind}"

    def test_call_nodes(self, cpg: CodePropertyGraph) -> None:
        # Calls are emitted with qualified name for method calls
        call_names = _names(cpg, NodeKind.CALL)
        assert "p.process" in call_names
        assert "p.validate" in call_names

    def test_method_call_resolution(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("p.process", "process") in pairs, f"CALLS pairs: {pairs}"
        assert ("p.validate", "validate") in pairs

    def test_local_variables_in_run(self, cpg: CodePropertyGraph) -> None:
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "result" in var_names
        assert "valid" in var_names

    def test_dfg_call_to_result(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("p.process", "result") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"

    def test_dfg_result_to_validate(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "p.validate") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"

    def test_return_nodes(self, cpg: CodePropertyGraph) -> None:
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        # process() and validate() each return
        assert len(returns) >= 2

    def test_include_import(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert any(i.attrs.get("module") == "string" for i in imports)


# ---------------------------------------------------------------------------
# nested_scopes.cpp
# ---------------------------------------------------------------------------


class TestNestedScopes:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("nested_scopes.cpp")

    def test_module_node(self, cpg: CodePropertyGraph) -> None:
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "nested_scopes"

    def test_outer_function_node(self, cpg: CodePropertyGraph) -> None:
        assert "outer" in _names(cpg, NodeKind.FUNCTION)

    def test_outer_parameter(self, cpg: CodePropertyGraph) -> None:
        params = _names(cpg, NodeKind.PARAMETER)
        assert "x" in params

    def test_lambda_captured_as_variable(self, cpg: CodePropertyGraph) -> None:
        # The lambda is assigned to 'inner', which the visitor emits as a variable
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "inner" in var_names

    def test_call_node_for_lambda_invocation(self, cpg: CodePropertyGraph) -> None:
        call_names = _names(cpg, NodeKind.CALL)
        assert "inner" in call_names

    def test_return_node(self, cpg: CodePropertyGraph) -> None:
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(returns) >= 1

    def test_dfg_call_to_return(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("inner", "return") in pairs, f"DATA_FLOWS_TO pairs: {pairs}"
