"""Tests for treeloom.models — YAML model loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from treeloom.models import list_builtin_models, load_models
from treeloom.models._loader import load_model_file


def _make_call_node(name: str):
    """Helper: construct a minimal CALL CpgNode with the given name."""
    from treeloom.model.location import SourceLocation
    from treeloom.model.nodes import CpgNode, NodeId, NodeKind

    return CpgNode(
        id=NodeId("test"),
        kind=NodeKind.CALL,
        name=name,
        location=SourceLocation(file=Path("t.py"), line=1),
    )


class TestListBuiltinModels:
    def test_returns_expected_models(self):
        names = list_builtin_models()
        assert "python-stdlib" in names
        assert "python-builtins" in names

    def test_returns_sorted_list(self):
        names = list_builtin_models()
        assert names == sorted(names)

    def test_returns_list(self):
        assert isinstance(list_builtin_models(), list)


class TestLoadModels:
    def test_load_python_stdlib(self):
        propagators = load_models(["python-stdlib"])
        assert len(propagators) > 0

    def test_load_python_builtins(self):
        propagators = load_models(["python-builtins"])
        assert len(propagators) > 0

    def test_load_multiple_models(self):
        single_a = load_models(["python-stdlib"])
        single_b = load_models(["python-builtins"])
        combined = load_models(["python-stdlib", "python-builtins"])
        assert len(combined) == len(single_a) + len(single_b)

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError, match="Unknown model"):
            load_models(["nonexistent-model"])

    def test_unknown_model_lists_valid_names(self):
        with pytest.raises(ValueError, match="python-stdlib"):
            load_models(["nonexistent-model"])

    def test_empty_list_returns_empty(self):
        assert load_models([]) == []


class TestPropagatorMatching:
    def test_json_loads_qualified_name(self):
        propagators = load_models(["python-stdlib"])
        node = _make_call_node("json.loads")
        matching = [p for p in propagators if p.match(node)]
        assert len(matching) >= 1
        assert matching[0].params_to_return == [0]

    def test_json_loads_unqualified_alias(self):
        propagators = load_models(["python-stdlib"])
        node = _make_call_node("loads")
        matching = [p for p in propagators if p.match(node)]
        assert len(matching) >= 1

    def test_os_path_join_propagates_two_params(self):
        propagators = load_models(["python-stdlib"])
        node = _make_call_node("os.path.join")
        matching = [p for p in propagators if p.match(node)]
        assert len(matching) >= 1
        assert matching[0].params_to_return == [0, 1]

    def test_str_builtin_propagates(self):
        propagators = load_models(["python-builtins"])
        node = _make_call_node("str")
        matching = [p for p in propagators if p.match(node)]
        assert len(matching) >= 1
        assert matching[0].params_to_return == [0]

    def test_unrelated_name_no_match(self):
        propagators = load_models(["python-stdlib", "python-builtins"])
        node = _make_call_node("totally_unrelated_function_xyz")
        matching = [p for p in propagators if p.match(node)]
        assert len(matching) == 0


class TestLoadModelFile:
    def test_invalid_schema_version(self, tmp_path: Path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("schema_version: 99\nfunctions: []\n")
        with pytest.raises(ValueError, match="schema_version"):
            load_model_file(bad_yaml)

    def test_non_mapping_top_level(self, tmp_path: Path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="mapping"):
            load_model_file(bad_yaml)

    def test_scalar_top_level(self, tmp_path: Path):
        bad_yaml = tmp_path / "scalar.yaml"
        bad_yaml.write_text("not a mapping\n")
        with pytest.raises(ValueError, match="mapping"):
            load_model_file(bad_yaml)

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_model_file(tmp_path / "does_not_exist.yaml")

    def test_empty_functions_list(self, tmp_path: Path):
        empty_yaml = tmp_path / "empty.yaml"
        empty_yaml.write_text("schema_version: 1\nfunctions: []\n")
        result = load_model_file(empty_yaml)
        assert result == []

    def test_function_without_propagation_defaults_param_to_return_true(self, tmp_path: Path):
        yaml_file = tmp_path / "simple.yaml"
        yaml_file.write_text(
            "schema_version: 1\nfunctions:\n  - name: myfunc\n    propagation: {}\n"
        )
        result = load_model_file(yaml_file)
        assert len(result) == 1
        assert result[0].param_to_return is True
        assert result[0].params_to_return is None

    def test_function_with_aliases(self, tmp_path: Path):
        yaml_file = tmp_path / "aliases.yaml"
        yaml_file.write_text(
            "schema_version: 1\n"
            "functions:\n"
            "  - name: myfunc\n"
            "    aliases: [myalias, another]\n"
            "    propagation:\n"
            "      params_to_return: [0]\n"
        )
        result = load_model_file(yaml_file)
        assert len(result) == 1
        node_main = _make_call_node("myfunc")
        node_alias = _make_call_node("myalias")
        node_other = _make_call_node("another")
        node_miss = _make_call_node("nomatch")
        assert result[0].match(node_main)
        assert result[0].match(node_alias)
        assert result[0].match(node_other)
        assert not result[0].match(node_miss)
