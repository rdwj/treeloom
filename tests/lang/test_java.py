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


class TestFieldDeclaration:
    """#87 — field_declaration handler."""

    def test_field_variables_emitted(self) -> None:
        src = b"""
class Account {
    private int balance = 100;
    private String name;
    public static final double RATE = 0.05;
}
"""
        cpg = CPGBuilder().add_source(src, "Account.java", "java").build()
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "balance" in var_names
        assert "name" in var_names
        assert "RATE" in var_names

    def test_field_with_initializer_has_dfg(self) -> None:
        src = b"""
class Foo {
    private int x = 5;
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # The literal 5 should flow to x
        assert any(t == "x" for _, t in pairs)

    def test_multiple_fields(self) -> None:
        src = b"""
class Config {
    private String host;
    private int port = 8080;
    private boolean ssl = true;
}
"""
        cpg = CPGBuilder().add_source(src, "Config.java", "java").build()
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert {"host", "port", "ssl"} <= var_names


class TestSwitchExpression:
    """#78 — switch_expression handler."""

    def test_switch_branch_node(self) -> None:
        src = b"""
class Foo {
    String test(int x) {
        switch (x) {
            case 1:
                return "one";
            case 2:
                return "two";
            default:
                return "other";
        }
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        branches = [
            b for b in cpg.nodes(kind=NodeKind.BRANCH)
            if b.attrs.get("branch_type") == "switch"
        ]
        assert len(branches) == 1

    def test_switch_visits_case_bodies(self) -> None:
        src = b"""
class Foo {
    void test(int x) {
        switch (x) {
            case 1:
                helper("one");
                break;
            case 2:
                helper("two");
                break;
        }
    }
    void helper(String s) {}
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert "helper" in call_names

    def test_switch_with_variable_in_case(self) -> None:
        src = b"""
class Foo {
    void test(int x) {
        switch (x) {
            case 1:
                int result = compute();
                break;
        }
    }
    int compute() { return 42; }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        assert "result" in _names(cpg, NodeKind.VARIABLE)


class TestTryStatement:
    """#79 — try_statement, try_with_resources_statement, catch_clause."""

    def test_catch_exception_variable(self) -> None:
        src = b"""
class Foo {
    void test() {
        try {
            riskyOp();
        } catch (Exception e) {
            log(e);
        }
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "e" in var_names

    def test_catch_body_visited(self) -> None:
        src = b"""
class Foo {
    void test() {
        try {
            riskyOp();
        } catch (Exception e) {
            handleError(e);
        }
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert "handleError" in call_names

    def test_finally_body_visited(self) -> None:
        src = b"""
class Foo {
    void test() {
        try {
            work();
        } catch (Exception e) {
        } finally {
            cleanup();
        }
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert "cleanup" in call_names

    def test_try_with_resources_variable(self) -> None:
        src = b"""
class Foo {
    void test() {
        try (BufferedReader br = new BufferedReader(null)) {
            String line = br.readLine();
        } catch (Exception e) {}
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "br" in var_names
        assert "line" in var_names

    def test_try_with_resources_dfg(self) -> None:
        src = b"""
class Foo {
    void test() {
        try (BufferedReader br = new BufferedReader(null)) {
            String line = br.readLine();
        } catch (Exception e) {}
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # new BufferedReader -> br
        assert any("BufferedReader" in s and t == "br" for s, t in pairs), (
            f"expected new BufferedReader -> br, got: {pairs}"
        )


class TestDoStatement:
    """#81 — do_statement handler."""

    def test_do_while_loop_node(self) -> None:
        src = b"""
class Foo {
    void test() {
        int x = 0;
        do {
            x++;
        } while (x < 10);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        loops = [
            n for n in cpg.nodes(kind=NodeKind.LOOP)
            if n.attrs.get("loop_type") == "do_while"
        ]
        assert len(loops) == 1

    def test_do_while_body_visited(self) -> None:
        src = b"""
class Foo {
    void test() {
        int count = 0;
        do {
            process(count);
            count++;
        } while (count < 5);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert "process" in call_names


class TestThrowStatement:
    """#88 — throw_statement handler."""

    def test_throw_constructor_emitted(self) -> None:
        src = b"""
class Foo {
    void test(String msg) {
        throw new IllegalArgumentException(msg);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert any("IllegalArgumentException" in c for c in call_names)

    def test_throw_dfg_from_variable(self) -> None:
        src = b"""
class Foo {
    void test(String msg) {
        throw new IllegalArgumentException(msg);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert any(s == "msg" and "IllegalArgumentException" in t for s, t in pairs), (
            f"expected msg -> new IllegalArgumentException, got: {pairs}"
        )


class TestStaticInitializer:
    """#91 — static_initializer handler."""

    def test_static_init_calls_visited(self) -> None:
        src = b"""
class Registry {
    static {
        register("default");
    }
    static void register(String name) {}
}
"""
        cpg = CPGBuilder().add_source(src, "Registry.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert "register" in call_names

    def test_static_init_variables_visited(self) -> None:
        src = b"""
class Config {
    static int counter;
    static {
        counter = 42;
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Config.java", "java").build()
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "counter" in var_names


class TestSynchronizedStatement:
    """#91 — synchronized_statement handler."""

    def test_synchronized_body_visited(self) -> None:
        src = b"""
class Foo {
    void test() {
        synchronized(this) {
            update();
        }
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert "update" in call_names

    def test_synchronized_variable_in_body(self) -> None:
        src = b"""
class Foo {
    void test() {
        synchronized(this) {
            int snapshot = getValue();
        }
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        assert "snapshot" in _names(cpg, NodeKind.VARIABLE)


class TestUpdateExpression:
    """#90 — update_expression handling in _visit_expression."""

    def test_update_returns_variable_id(self) -> None:
        src = b"""
class Foo {
    void test() {
        int i = 0;
        i++;
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        assert "i" in _names(cpg, NodeKind.VARIABLE)


class TestArrayAccess:
    """#90 — array_access handling in _visit_expression."""

    def test_array_access_propagates_taint(self) -> None:
        src = b"""
class Foo {
    void test(String[] args) {
        String first = args[0];
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # args should flow to first via array access
        assert any(s == "args" and t == "first" for s, t in pairs), (
            f"expected args -> first via array access, got: {pairs}"
        )


class TestTernaryExpression:
    """#86 — ternary_expression handling in _visit_expression."""

    def test_ternary_both_branches_flow(self) -> None:
        src = b"""
class Foo {
    void test(boolean flag, String a, String b) {
        String result = flag ? a : b;
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        # Both branches should flow through the ternary merge to result
        a_flows = any(s == "a" and "<ternary>" in t for s, t in pairs)
        b_flows = any(s == "b" and "<ternary>" in t for s, t in pairs)
        assert a_flows, f"expected a -> <ternary>, got: {pairs}"
        assert b_flows, f"expected b -> <ternary>, got: {pairs}"
        # Ternary merge flows to result
        assert any("<ternary>" in s and t == "result" for s, t in pairs), (
            f"expected <ternary> -> result, got: {pairs}"
        )


class TestMethodReference:
    """#89 — method_reference handling in _visit_expression."""

    def test_method_reference_emits_call(self) -> None:
        src = b"""
class Foo {
    void test(java.util.List<String> items) {
        items.stream().map(String::toUpperCase);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert any("toUpperCase" in c for c in call_names), (
            f"expected call containing toUpperCase, got: {call_names}"
        )

    def test_method_reference_target_name(self) -> None:
        src = b"""
class Foo {
    void test(java.util.List<String> items) {
        items.forEach(System.out::println);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert any("println" in c for c in call_names)


class TestFieldAccess:
    """#85 — field_access handling in _visit_expression."""

    def test_field_access_emits_variable(self) -> None:
        src = b"""
class Foo {
    int value = 10;
    int test() {
        return this.value;
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "this.value" in var_names

    def test_field_access_dfg_through_assignment(self) -> None:
        src = b"""
class Foo {
    int value;
    void test(int x) {
        this.value = x;
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert ("x", "this.value") in pairs, (
            f"expected x -> this.value, got: {pairs}"
        )


class TestUnaryExpression:
    """#92 — unary_expression handling in _visit_expression."""

    def test_unary_propagates_operand(self) -> None:
        src = b"""
class Foo {
    void test(boolean flag) {
        boolean neg = !flag;
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert any(s == "flag" and t == "neg" for s, t in pairs), (
            f"expected flag -> neg via unary, got: {pairs}"
        )


class TestInstanceofExpression:
    """#91 — instanceof_expression handling in _visit_expression."""

    def test_instanceof_visits_lhs(self) -> None:
        src = b"""
class Foo {
    void test(Object obj) {
        if (obj instanceof String) {
            process(obj);
        }
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert "process" in call_names


class TestRecordDeclaration:
    """#92 — record_declaration handler."""

    def test_record_emits_class(self) -> None:
        src = b"""
record Point(int x, int y) {
    public String label() {
        return "point";
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Point.java", "java").build()
        assert "Point" in _names(cpg, NodeKind.CLASS)

    def test_record_method_visited(self) -> None:
        src = b"""
record Point(int x, int y) {
    public String label() {
        return "point";
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Point.java", "java").build()
        assert "label" in _names(cpg, NodeKind.FUNCTION)

    def test_record_method_scoped_to_record(self) -> None:
        src = b"""
record Point(int x, int y) {
    public String label() {
        return "point";
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Point.java", "java").build()
        fn = next(n for n in cpg.nodes(kind=NodeKind.FUNCTION) if n.name == "label")
        scope = cpg.scope_of(fn.id)
        assert scope is not None
        assert scope.name == "Point"
        assert scope.kind == NodeKind.CLASS

    def test_record_components_emitted(self) -> None:
        src = b"""
record Point(int x, int y) {}
"""
        cpg = CPGBuilder().add_source(src, "Point.java", "java").build()
        params = {n.name: n for n in cpg.nodes(kind=NodeKind.PARAMETER)}
        assert "x" in params
        assert "y" in params
        assert params["x"].attrs["type_annotation"] == "int"
        assert params["y"].attrs["type_annotation"] == "int"


class TestVarargsParameter:
    """#82 — spread_parameter emits a PARAMETER node."""

    def test_varargs_parameter_emitted(self) -> None:
        src = b"""
class Foo {
    void log(String format, Object... args) {
        System.out.println(format);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        params = {n.name: n for n in cpg.nodes(kind=NodeKind.PARAMETER)}
        assert "format" in params
        assert "args" in params

    def test_varargs_has_type_annotation(self) -> None:
        src = b"""
class Foo {
    void log(String format, Object... args) {}
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        params = {n.name: n for n in cpg.nodes(kind=NodeKind.PARAMETER)}
        assert params["args"].attrs["type_annotation"] == "Object..."

    def test_varargs_position(self) -> None:
        src = b"""
class Foo {
    void log(String format, Object... args) {}
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        params = {n.name: n for n in cpg.nodes(kind=NodeKind.PARAMETER)}
        assert params["format"].attrs["position"] == 0
        assert params["args"].attrs["position"] == 1

    def test_varargs_in_defined_vars(self) -> None:
        """Varargs param should be in defined_vars so DFG works."""
        src = b"""
class Foo {
    void log(String format, Object... args) {
        System.out.println(args);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.DATA_FLOWS_TO)
        assert any(s == "args" for s, _ in pairs), (
            f"expected args to appear in DFG, got: {pairs}"
        )


class TestForLoopConditionUpdate:
    """#83 — for-loop condition and update visiting."""

    def test_for_loop_condition_call_visited(self) -> None:
        src = b"""
class Foo {
    void test() {
        for (int i = 0; hasMore(i); i++) {
            process(i);
        }
    }
    boolean hasMore(int n) { return false; }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call_names = _names(cpg, NodeKind.CALL)
        assert "hasMore" in call_names

    def test_for_loop_update_visited(self) -> None:
        """Update expression (i++) should be visited."""
        src = b"""
class Foo {
    void test() {
        int count = 0;
        for (int i = 0; i < 10; i++) {
            count = count + 1;
        }
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "i" in var_names
        assert "count" in var_names


class TestLambdaFunctionNode:
    """#84 — lambda_expression emits FUNCTION node with parameters."""

    def test_lambda_emits_function_node(self) -> None:
        src = b"""
class Foo {
    void test(java.util.List<String> items) {
        items.forEach(x -> process(x));
    }
    void process(String s) {}
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        funcs = _names(cpg, NodeKind.FUNCTION)
        # Should have test, process, and a lambda$N$N function
        assert any(f.startswith("lambda$") for f in funcs), (
            f"expected lambda function node, got: {funcs}"
        )

    def test_lambda_has_parameter(self) -> None:
        src = b"""
class Foo {
    void test(java.util.List<String> items) {
        items.forEach(x -> process(x));
    }
    void process(String s) {}
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        params = {n.name: n for n in cpg.nodes(kind=NodeKind.PARAMETER)}
        assert "x" in params

    def test_lambda_parameter_scoped_to_lambda(self) -> None:
        src = b"""
class Foo {
    void test(java.util.List<String> items) {
        items.forEach(x -> process(x));
    }
    void process(String s) {}
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        param = next(n for n in cpg.nodes(kind=NodeKind.PARAMETER) if n.name == "x")
        scope = cpg.scope_of(param.id)
        assert scope is not None
        assert scope.kind == NodeKind.FUNCTION
        assert scope.name.startswith("lambda$")

    def test_lambda_body_visited(self) -> None:
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
        assert any("process" in c for c in call_names)

    def test_lambda_with_block_body(self) -> None:
        src = b"""
class Foo {
    void test(java.util.List<String> items) {
        items.forEach(x -> {
            String upper = x.toUpperCase();
            System.out.println(upper);
        });
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        var_names = _names(cpg, NodeKind.VARIABLE)
        assert "upper" in var_names

    def test_lambda_multi_param(self) -> None:
        src = b"""
class Foo {
    void test() {
        java.util.Comparator<String> cmp = (a, b) -> a.compareTo(b);
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        params = {n.name for n in cpg.nodes(kind=NodeKind.PARAMETER)}
        assert "a" in params
        assert "b" in params


class TestTypeBasedCallResolution:
    """#80 — Type-based call resolution and import-following."""

    def test_class_bases_extracted(self) -> None:
        src = b"""
class Animal {}
class Dog extends Animal {
    void bark() {}
}
"""
        cpg = CPGBuilder().add_source(src, "Dog.java", "java").build()
        dog = next(n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Dog")
        assert dog.attrs.get("bases") == ["Animal"]

    def test_interface_implements_bases(self) -> None:
        src = b"""
interface Runnable {
    void run();
}
class Worker implements Runnable {
    public void run() {}
}
"""
        cpg = CPGBuilder().add_source(src, "Worker.java", "java").build()
        worker = next(n for n in cpg.nodes(kind=NodeKind.CLASS) if n.name == "Worker")
        assert worker.attrs.get("bases") == ["Runnable"]

    def test_mro_resolution(self) -> None:
        """Method call on a typed variable resolves via class hierarchy."""
        src = b"""
class Base {
    void greet() {}
}
class Child extends Base {
}
class App {
    void test() {
        Child c = new Child();
        c.greet();
    }
}
"""
        cpg = CPGBuilder().add_source(src, "App.java", "java").build()
        pairs = _edge_pairs(cpg, EdgeKind.CALLS)
        # c.greet() should resolve to Base.greet via MRO
        assert ("c.greet", "greet") in pairs, (
            f"expected c.greet -> greet via MRO, got: {pairs}"
        )

    def test_receiver_inferred_type_set(self) -> None:
        src = b"""
class Foo {
    void test() {
        StringBuilder sb = new StringBuilder();
        sb.append("hello");
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        call = next(
            n for n in cpg.nodes(kind=NodeKind.CALL) if "append" in n.name
        )
        assert call.attrs.get("receiver_inferred_type") == "StringBuilder"

    def test_variable_inferred_type_from_declaration(self) -> None:
        src = b"""
class Foo {
    void test() {
        String name = "hello";
    }
}
"""
        cpg = CPGBuilder().add_source(src, "Foo.java", "java").build()
        var = next(n for n in cpg.nodes(kind=NodeKind.VARIABLE) if n.name == "name")
        assert var.attrs.get("inferred_type") == "String"
