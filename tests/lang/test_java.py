"""Tests for the Java language visitor.

Uses CPGBuilder to parse fixture files and asserts on the resulting graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.graph.builder import CPGBuilder
from treeloom.graph.cpg import CodePropertyGraph
from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import NodeKind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "java"


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
        return _build("SimpleClass.java")

    def test_module_node(self, cpg: CodePropertyGraph) -> None:
        modules = list(cpg.nodes(kind=NodeKind.MODULE))
        assert len(modules) == 1
        assert modules[0].name == "SimpleClass"

    def test_class_node(self, cpg: CodePropertyGraph) -> None:
        assert _names(cpg, NodeKind.CLASS) == {"SimpleClass"}

    def test_class_contained_in_module(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.CONTAINS)
        assert ("SimpleClass", "SimpleClass") in pairs

    def test_methods(self, cpg: CodePropertyGraph) -> None:
        assert _names(cpg, NodeKind.FUNCTION) == {
            "SimpleClass", "getValue", "add", "describe"
        }

    def test_constructor_scoped_to_class(self, cpg: CodePropertyGraph) -> None:
        ctors = [n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "SimpleClass"]
        assert len(ctors) == 1
        scope = cpg.scope_of(ctors[0].id)
        assert scope is not None
        assert scope.kind == NodeKind.CLASS

    def test_methods_scoped_to_class(self, cpg: CodePropertyGraph) -> None:
        for fn in cpg.nodes(kind=NodeKind.FUNCTION):
            scope = cpg.scope_of(fn.id)
            assert scope is not None
            assert scope.kind == NodeKind.CLASS

    def test_typed_parameters(self, cpg: CodePropertyGraph) -> None:
        params = {n.name: n for n in cpg.nodes(kind=NodeKind.PARAMETER)}
        assert "initialValue" in params
        assert params["initialValue"].attrs["type_annotation"] == "int"
        assert params["initialValue"].attrs["position"] == 0

        assert "a" in params
        assert params["a"].attrs["type_annotation"] == "int"
        assert params["a"].attrs["position"] == 0

        assert "b" in params
        assert params["b"].attrs["type_annotation"] == "int"
        assert params["b"].attrs["position"] == 1

        assert "prefix" in params
        assert params["prefix"].attrs["type_annotation"] == "String"

    def test_has_parameter_edges(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.HAS_PARAMETER)
        assert ("add", "a") in pairs
        assert ("add", "b") in pairs
        assert ("SimpleClass", "initialValue") in pairs
        assert ("describe", "prefix") in pairs

    def test_local_variable(self, cpg: CodePropertyGraph) -> None:
        assert "result" in _names(cpg, NodeKind.VARIABLE)
        assert "msg" in _names(cpg, NodeKind.VARIABLE)

    def test_return_nodes(self, cpg: CodePropertyGraph) -> None:
        returns = list(cpg.nodes(kind=NodeKind.RETURN))
        assert len(returns) == 3

    def test_import_node(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert len(imports) == 1
        imp = imports[0]
        assert imp.attrs["module"] == "java.util"
        assert imp.attrs["names"] == ["List"]
        assert imp.attrs["is_from"] is True

    def test_data_flow_to_return(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in pairs

    def test_data_flow_param_to_variable(self, cpg: CodePropertyGraph) -> None:
        """Parameter flows into local variable via assignment."""
        # initialValue -> this.value (via assignment this.value = initialValue)
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("initialValue", "this.value") in pairs


class TestInterfaces:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("Interfaces.java")

    def test_interface_emitted_as_class(self, cpg: CodePropertyGraph) -> None:
        class_names = _names(cpg, NodeKind.CLASS)
        assert "Greeter" in class_names
        assert "DefaultGreeter" in class_names

    def test_interface_methods(self, cpg: CodePropertyGraph) -> None:
        func_names = _names(cpg, NodeKind.FUNCTION)
        assert "greet" in func_names
        assert "count" in func_names

    def test_constructor_present(self, cpg: CodePropertyGraph) -> None:
        assert "DefaultGreeter" in _names(cpg, NodeKind.FUNCTION)

    def test_parameters_with_types(self, cpg: CodePropertyGraph) -> None:
        params = {n.name: n for n in cpg.nodes(kind=NodeKind.PARAMETER)}
        assert "name" in params
        assert "prefix" in params
        assert params["name"].attrs["type_annotation"] == "String"
        assert params["prefix"].attrs["type_annotation"] == "String"

    def test_import(self, cpg: CodePropertyGraph) -> None:
        imports = list(cpg.nodes(kind=NodeKind.IMPORT))
        assert any(i.attrs["module"] == "java.util" for i in imports)

    def test_variable_in_method(self, cpg: CodePropertyGraph) -> None:
        assert "result" in _names(cpg, NodeKind.VARIABLE)

    def test_data_flow_to_return(self, cpg: CodePropertyGraph) -> None:
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("result", "return") in pairs


class TestControlFlow:
    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("ControlFlow.java")

    def test_class_and_methods(self, cpg: CodePropertyGraph) -> None:
        assert "ControlFlow" in _names(cpg, NodeKind.CLASS)
        func_names = _names(cpg, NodeKind.FUNCTION)
        assert {"classify", "sumTo", "printAll", "countDown"} == func_names

    def test_branch_nodes_emitted(self, cpg: CodePropertyGraph) -> None:
        branches = list(cpg.nodes(kind=NodeKind.BRANCH))
        assert len(branches) >= 1
        branch_types = {b.attrs.get("branch_type") for b in branches}
        assert "if" in branch_types

    def test_if_has_else(self, cpg: CodePropertyGraph) -> None:
        if_branches = [
            b for b in cpg.nodes(kind=NodeKind.BRANCH)
            if b.attrs.get("branch_type") == "if"
        ]
        # classify() outer if has an else branch
        assert any(b.attrs["has_else"] is True for b in if_branches)

    def test_for_loop_node(self, cpg: CodePropertyGraph) -> None:
        loops = [n for n in cpg.nodes(kind=NodeKind.LOOP) if n.attrs.get("loop_type") == "for"]
        assert len(loops) >= 1

    def test_enhanced_for_iterator_var(self, cpg: CodePropertyGraph) -> None:
        enhanced = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("iterator_var") is not None
        ]
        assert len(enhanced) == 1
        assert enhanced[0].attrs["iterator_var"] == "item"

    def test_while_loop_node(self, cpg: CodePropertyGraph) -> None:
        while_loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "while"
        ]
        assert len(while_loops) == 1

    def test_method_call_emitted(self, cpg: CodePropertyGraph) -> None:
        call_names = _names(cpg, NodeKind.CALL)
        assert any("println" in c for c in call_names)

    def test_local_variable_in_loop(self, cpg: CodePropertyGraph) -> None:
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "total" in var_names

    def test_enhanced_for_variable_emitted(self, cpg: CodePropertyGraph) -> None:
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "item" in var_names


class TestMethodInvocations:
    """Verify method invocation handling via inline source."""

    def test_simple_method_call(self) -> None:
        src = b"""
class Caller {
    void run() {
        helper();
    }
    void helper() {
        int x = 1;
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Caller.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert "helper" in call_names

    def test_qualified_method_call(self) -> None:
        src = b"""
class Foo {
    void test() {
        System.out.println("hello");
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert any("println" in c for c in call_names)

    def test_object_creation(self) -> None:
        src = b"""
class Builder {
    void make() {
        StringBuilder sb = new StringBuilder();
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Builder.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert any("StringBuilder" in c for c in call_names)

    def test_call_resolution(self) -> None:
        src = b"""
class App {
    int compute(int x) {
        return x + 1;
    }
    void run() {
        int result = compute(5);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "App.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        assert ("compute", "compute") in pairs

    def test_data_flow_arg_to_call(self) -> None:
        src = b"""
class Printer {
    void run() {
        String msg = "hello";
        System.out.println(msg);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Printer.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # msg should flow into the println call
        assert any(src_name == "msg" for src_name, _ in pairs)


class TestStringConcatDFG:
    """Verify that string concatenation (`+`) propagates data flow."""

    def test_string_concat_emits_concat_call(self) -> None:
        src = b"""
class Foo {
    void test(String userInput) {
        String sql = "SELECT * FROM t WHERE id=" + userInput;
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert "<string_concat>" in call_names

    def test_string_concat_flows_from_variable(self) -> None:
        """Variable used in string concat must produce a DFG edge."""
        src = b"""
class Foo {
    void test(String userInput) {
        String sql = "SELECT * FROM t WHERE id=" + userInput;
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # userInput -> <string_concat>
        assert any(s == "userInput" and "concat" in t for s, t in pairs), (
            f"expected userInput -> <string_concat>, got: {pairs}"
        )

    def test_string_concat_flows_to_sink(self) -> None:
        """Full chain: param -> concat -> query call."""
        src = b"""
class Foo {
    void test(String id) {
        jdbcTemplate.query("SELECT * WHERE id=" + id);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # id -> <string_concat>
        assert any(s == "id" and "concat" in t for s, t in pairs), (
            f"expected id -> <string_concat>, got: {pairs}"
        )
        # <string_concat> -> jdbcTemplate.query
        assert any("concat" in s and "query" in t for s, t in pairs), (
            f"expected <string_concat> -> query call, got: {pairs}"
        )

    def test_method_call_return_flows_through_concat_to_sink(self) -> None:
        """queryParams.get() -> variable -> concat -> sink: full taint chain."""
        src = b"""
class Foo {
    void test(java.util.Map<String,String> queryParams) {
        String id = queryParams.get("id");
        jdbcTemplate.query("SELECT * WHERE id=" + id);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # queryParams.get -> id
        assert ("queryParams.get", "id") in pairs, (
            f"expected queryParams.get -> id, got: {pairs}"
        )
        # id -> <string_concat>
        assert any(s == "id" and "concat" in t for s, t in pairs), (
            f"expected id -> <string_concat>, got: {pairs}"
        )
        # <string_concat> -> sink
        assert any("concat" in s and "query" in t for s, t in pairs), (
            f"expected <string_concat> -> query, got: {pairs}"
        )


class TestMethodReceiverDFG:
    """Verify method call receivers contribute to data flow."""

    def test_receiver_flows_into_call(self) -> None:
        """obj.method() should emit DFG from obj to the call node."""
        src = b"""
class Foo {
    void test(java.util.Map<String,String> queryParams) {
        String value = queryParams.get("key");
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # queryParams (param) -> queryParams.get (call)
        assert ("queryParams", "queryParams.get") in pairs, (
            f"expected queryParams -> queryParams.get, got: {pairs}"
        )

    def test_call_return_flows_to_variable(self) -> None:
        """Return value of call assigned to variable produces DFG edge."""
        src = b"""
class Foo {
    void test(java.util.Map<String,String> params) {
        String id = params.get("id");
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("params.get", "id") in pairs, (
            f"expected params.get -> id, got: {pairs}"
        )


class TestTryBlockVisiting:
    """Statements inside try blocks must be visited."""

    def test_variables_inside_try_are_emitted(self) -> None:
        src = b"""
class Foo {
    void test(String input) {
        try {
            String sql = "SELECT * WHERE id=" + input;
            jdbcTemplate.query(sql);
        } catch (Exception e) {
            logger.error("error", e);
        }
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "sql" in var_names, f"expected sql in variables, got: {var_names}"

    def test_calls_inside_try_are_emitted(self) -> None:
        src = b"""
class Foo {
    void test(String input) {
        try {
            jdbcTemplate.query(input);
        } catch (Exception e) {}
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert any("query" in c for c in call_names), (
            f"expected query call inside try, got: {call_names}"
        )

    def test_dfg_preserved_across_try_block(self) -> None:
        """String concat DFG should work inside a try block."""
        src = b"""
class Foo {
    void test(String input) {
        try {
            jdbcTemplate.query("SELECT * WHERE x=" + input);
        } catch (Exception e) {}
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert any(s == "input" and "concat" in t for s, t in pairs), (
            f"expected input -> <string_concat> inside try, got: {pairs}"
        )


class TestConstructorArgDFG:
    """Constructor args should flow into the constructor call node."""

    def test_constructor_arg_flows_into_call(self) -> None:
        src = b"""
class Foo {
    void test(String cmd) {
        Process p = new ProcessBuilder(cmd).start();
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # cmd -> new ProcessBuilder
        assert any(s == "cmd" and "ProcessBuilder" in t for s, t in pairs), (
            f"expected cmd -> new ProcessBuilder, got: {pairs}"
        )

    def test_constructor_with_string_concat_arg(self) -> None:
        src = b"""
class Foo {
    void test(String ipAddress) {
        Process p = new ProcessBuilder(new String[]{"ping -c 2 " + ipAddress}).start();
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # ipAddress -> <string_concat>
        assert any(s == "ipAddress" and "concat" in t for s, t in pairs), (
            f"expected ipAddress -> <string_concat>, got: {pairs}"
        )


class TestLambdaBodyVisiting:
    """Lambda expression bodies should be visited for calls and DFG."""

    def test_call_inside_lambda_is_emitted(self) -> None:
        src = b"""
class Foo {
    void test(java.util.List<String> items) {
        items.forEach(x -> process(x));
    }
    void process(String s) {}
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert any("process" in c for c in call_names), (
            f"expected process call in lambda body, got: {call_names}"
        )


class TestEndLocation:
    """Verify the Java visitor populates end_location on all node kinds."""

    @pytest.fixture()
    def cpg(self) -> CodePropertyGraph:
        return _build("SimpleClass.java")

    def test_module_has_end_location(self, cpg: CodePropertyGraph) -> None:
        mod = next(cpg.nodes(kind=NodeKind.MODULE))
        assert mod.end_location is not None
        assert mod.end_location.line >= mod.location.line

    def test_class_has_end_location(self, cpg: CodePropertyGraph) -> None:
        cls = next(n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "SimpleClass")
        assert cls.end_location is not None
        assert cls.end_location.line >= cls.location.line

    def test_function_has_end_location(self, cpg: CodePropertyGraph) -> None:
        func = next(n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "getValue")
        assert func.end_location is not None
        assert func.end_location.line >= func.location.line

    def test_parameter_has_end_location(self, cpg: CodePropertyGraph) -> None:
        params = list(cpg.nodes(kind=NodeKind.PARAMETER))
        assert len(params) > 0
        for p in params:
            assert p.end_location is not None, f"Parameter {p.name!r} missing end_location"

    def test_end_location_after_start(self, cpg: CodePropertyGraph) -> None:
        """end_location should always be at or after location (start)."""
        for node in cpg.nodes():
            if node.location is not None and node.end_location is not None:
                assert (node.end_location.line, node.end_location.column) >= (
                    node.location.line, node.location.column
                ), f"Node {node.name!r} has end before start"


class TestSourceText:
    """Verify include_source mode populates source_text on class/function nodes."""

    @pytest.fixture()
    def cpg_with_source(self) -> CodePropertyGraph:
        return (
            CPGBuilder(include_source=True)
            .add_file(FIXTURES / "SimpleClass.java")
            .build()
        )

    @pytest.fixture()
    def cpg_without_source(self) -> CodePropertyGraph:
        return _build("SimpleClass.java")

    def test_class_has_source_text(self, cpg_with_source: CodePropertyGraph) -> None:
        cls = next(n for n in cpg_with_source.nodes(kind=NodeKind.CLASS) if n.name == "SimpleClass")
        assert "source_text" in cls.attrs
        assert "class SimpleClass" in cls.attrs["source_text"]

    def test_function_has_source_text(self, cpg_with_source: CodePropertyGraph) -> None:
        func = next(n for n in cpg_with_source.nodes(kind=NodeKind.FUNCTION) if n.name == "getValue")
        assert "source_text" in func.attrs

    def test_module_no_source_text(self, cpg_with_source: CodePropertyGraph) -> None:
        mod = next(cpg_with_source.nodes(kind=NodeKind.MODULE))
        assert "source_text" not in mod.attrs

    def test_default_no_source_text(self, cpg_without_source: CodePropertyGraph) -> None:
        for node in cpg_without_source.nodes():
            assert "source_text" not in node.attrs, (
                f"Node {node.name!r} has source_text without include_source"
            )


class TestRegistryIntegration:
    """Verify Java visitor is registered in the default registry."""

    def test_java_extension_registered(self) -> None:
        from treeloom.lang.registry import LanguageRegistry

        registry = LanguageRegistry.default()
        visitor = registry.get_visitor(".java")
        assert visitor is not None
        assert visitor.name == "java"

    def test_java_visitor_by_name(self) -> None:
        from treeloom.lang.registry import LanguageRegistry

        registry = LanguageRegistry.default()
        visitor = registry.get_visitor_by_name("java")
        assert visitor is not None

    def test_add_source_with_java_language(self) -> None:
        src = b"""
class Hello {
    public static void main(String[] args) {
        System.out.println("Hello");
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Hello.java", "java").build()
        assert "Hello" in _names(cpg, NodeKind.CLASS)
        assert "main" in _names(cpg, NodeKind.FUNCTION)
