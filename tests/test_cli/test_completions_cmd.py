"""Tests for ``treeloom completions`` command."""

from __future__ import annotations

import argparse

import pytest

from treeloom.cli.completions_cmd import _SUBCOMMANDS, _VALID_SHELLS, run_cmd


@pytest.fixture()
def capsys_output(capsys: pytest.CaptureFixture[str]):
    """Helper that runs run_cmd and returns (rc, stdout, stderr)."""
    def _run(shell: str) -> tuple[int, str, str]:
        args = argparse.Namespace(shell=shell)
        rc = run_cmd(args)
        out = capsys.readouterr()
        return rc, out.out, out.err
    return _run


class TestBashCompletions:
    def test_bash_exits_zero(self, capsys_output) -> None:
        rc, _, _ = capsys_output("bash")
        assert rc == 0

    def test_bash_contains_complete_function(self, capsys_output) -> None:
        _, out, _ = capsys_output("bash")
        assert "complete -F _treeloom_completion treeloom" in out

    def test_bash_contains_completion_function_definition(self, capsys_output) -> None:
        _, out, _ = capsys_output("bash")
        assert "_treeloom_completion()" in out

    def test_bash_contains_all_subcommands(self, capsys_output) -> None:
        _, out, _ = capsys_output("bash")
        for cmd in _SUBCOMMANDS:
            assert cmd in out, f"subcommand '{cmd}' missing from bash output"

    def test_bash_contains_build_flags(self, capsys_output) -> None:
        _, out, _ = capsys_output("bash")
        assert "--output" in out
        assert "--exclude" in out
        assert "--progress" in out

    def test_bash_contains_query_flags(self, capsys_output) -> None:
        _, out, _ = capsys_output("bash")
        assert "--kind" in out
        assert "--name" in out
        assert "--limit" in out

    def test_bash_contains_taint_flags(self, capsys_output) -> None:
        _, out, _ = capsys_output("bash")
        assert "--policy" in out
        assert "--show-sanitized" in out
        assert "--apply" in out


class TestZshCompletions:
    def test_zsh_exits_zero(self, capsys_output) -> None:
        rc, _, _ = capsys_output("zsh")
        assert rc == 0

    def test_zsh_contains_compdef(self, capsys_output) -> None:
        _, out, _ = capsys_output("zsh")
        assert "compdef _treeloom treeloom" in out

    def test_zsh_contains_function_definition(self, capsys_output) -> None:
        _, out, _ = capsys_output("zsh")
        assert "_treeloom()" in out

    def test_zsh_contains_all_subcommands(self, capsys_output) -> None:
        _, out, _ = capsys_output("zsh")
        for cmd in _SUBCOMMANDS:
            assert cmd in out, f"subcommand '{cmd}' missing from zsh output"

    def test_zsh_has_descriptions(self, capsys_output) -> None:
        _, out, _ = capsys_output("zsh")
        assert "Build a CPG from source files" in out
        assert "Run taint analysis on a CPG" in out

    def test_zsh_starts_with_compdef_directive(self, capsys_output) -> None:
        _, out, _ = capsys_output("zsh")
        assert out.startswith("#compdef treeloom")


class TestFishCompletions:
    def test_fish_exits_zero(self, capsys_output) -> None:
        rc, _, _ = capsys_output("fish")
        assert rc == 0

    def test_fish_contains_complete_c_treeloom(self, capsys_output) -> None:
        _, out, _ = capsys_output("fish")
        assert "complete -c treeloom" in out

    def test_fish_contains_all_subcommands(self, capsys_output) -> None:
        _, out, _ = capsys_output("fish")
        for cmd in _SUBCOMMANDS:
            assert f"'{cmd}'" in out or f" {cmd} " in out or f"-a '{cmd}'" in out, (
                f"subcommand '{cmd}' missing from fish output"
            )

    def test_fish_contains_build_flags(self, capsys_output) -> None:
        _, out, _ = capsys_output("fish")
        assert "__fish_seen_subcommand_from build" in out

    def test_fish_contains_taint_flags(self, capsys_output) -> None:
        _, out, _ = capsys_output("fish")
        assert "__fish_seen_subcommand_from taint" in out
        assert "show-sanitized" in out

    def test_fish_subcommand_helper_function(self, capsys_output) -> None:
        _, out, _ = capsys_output("fish")
        assert "__treeloom_no_subcommand" in out


class TestInvalidShell:
    def test_invalid_shell_returns_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(shell="powershell")
        rc = run_cmd(args)
        assert rc == 1
        err = capsys.readouterr().err
        assert "unsupported shell" in err
        assert "powershell" in err

    def test_invalid_shell_lists_valid_options(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(shell="nushell")
        run_cmd(args)
        err = capsys.readouterr().err
        for shell in _VALID_SHELLS:
            assert shell in err


class TestSubcommandCoverage:
    """Verify that all expected subcommands appear in every shell script."""

    @pytest.mark.parametrize("shell", _VALID_SHELLS)
    def test_all_subcommands_present(
        self, shell: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = argparse.Namespace(shell=shell)
        run_cmd(args)
        out = capsys.readouterr().out
        for cmd in _SUBCOMMANDS:
            assert cmd in out, f"'{cmd}' missing from {shell} completion script"

    @pytest.mark.parametrize("shell", _VALID_SHELLS)
    def test_output_is_non_empty(
        self, shell: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = argparse.Namespace(shell=shell)
        rc = run_cmd(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert len(out) > 100, f"{shell} completion output is unexpectedly short"
