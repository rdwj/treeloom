"""``treeloom completions`` -- print shell completion scripts to stdout."""

from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from typing import Any

_SUBCOMMANDS = (
    "build",
    "info",
    "query",
    "taint",
    "viz",
    "dot",
    "config",
    "annotate",
    "diff",
    "subgraph",
    "pattern",
    "completions",
)

_BASH_SCRIPT = """\
# treeloom bash completion
# Source this file or place it in ~/.local/share/bash-completion/completions/treeloom

_treeloom_completion() {
    local cur prev commands
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    commands="build info query taint viz dot config annotate diff subgraph pattern completions"

    if [ $COMP_CWORD -eq 1 ]; then
        COMPREPLY=($(compgen -W "$commands --version --verbose -v --json-errors --help" -- "$cur"))
        return
    fi

    local cmd="${COMP_WORDS[1]}"
    case "$cmd" in
        build)
            COMPREPLY=($(compgen -W "-o --output --exclude --quiet -q --progress --help" -f -- "$cur"))
            ;;
        info)
            COMPREPLY=($(compgen -W "--json --help" -f -- "$cur"))
            ;;
        query)
            COMPREPLY=($(compgen -W "--kind -k --name -n --file -f --json --limit -l --help" -f -- "$cur"))
            ;;
        taint)
            COMPREPLY=($(compgen -W "--policy -p -o --output --show-sanitized --json --apply --help" -f -- "$cur"))
            ;;
        viz)
            COMPREPLY=($(compgen -W "-o --output --title --open --help" -f -- "$cur"))
            ;;
        dot)
            COMPREPLY=($(compgen -W "-o --output --edge-kind --node-kind --help" -f -- "$cur"))
            ;;
        config)
            COMPREPLY=($(compgen -W "--show --init --set --unset --global --help" -- "$cur"))
            ;;
        annotate)
            COMPREPLY=($(compgen -W "--rules -r -o --output --json --help" -f -- "$cur"))
            ;;
        diff)
            COMPREPLY=($(compgen -W "--json --help" -f -- "$cur"))
            ;;
        subgraph)
            COMPREPLY=($(compgen -W "-o --output --depth --root --function --class --file --help" -f -- "$cur"))
            ;;
        pattern)
            COMPREPLY=($(compgen -W "--kind --name --annotation --edge-kind --depth --json --help" -f -- "$cur"))
            ;;
        completions)
            COMPREPLY=($(compgen -W "bash zsh fish --help" -- "$cur"))
            ;;
    esac
}

complete -F _treeloom_completion treeloom
"""

_ZSH_SCRIPT = """\
#compdef treeloom
# treeloom zsh completion
# Place this file at ~/.zfunc/_treeloom and add the following to ~/.zshrc:
#   fpath=(~/.zfunc $fpath)
#   autoload -Uz compinit && compinit

_treeloom() {
    local -a commands
    commands=(
        'build:Build a CPG from source files'
        'info:Display CPG summary statistics'
        'query:Search and filter CPG nodes'
        'taint:Run taint analysis on a CPG'
        'viz:Generate interactive HTML visualization'
        'dot:Export CPG to Graphviz DOT format'
        'config:View or modify configuration'
        'annotate:Apply YAML annotation rules to a CPG'
        'diff:Compare two CPGs and report structural changes'
        'subgraph:Extract a subgraph rooted at a specific node'
        'pattern:Match chain patterns against the CPG'
        'completions:Print shell completion script to stdout'
    )

    local -a global_opts
    global_opts=(
        '--version[Show version and exit]'
        '--verbose[Enable debug logging]'
        '-v[Enable debug logging]'
        '--json-errors[Output errors as JSON to stderr]'
        '--help[Show help and exit]'
    )

    if (( CURRENT == 2 )); then
        _describe 'command' commands
        _arguments $global_opts
        return
    fi

    local cmd="${words[2]}"
    case "$cmd" in
        build)
            _arguments \\
                ':path:_files' \\
                '-o[Output JSON file]:file:_files' \\
                '--output[Output JSON file]:file:_files' \\
                '--exclude[Exclusion glob pattern]:pattern:' \\
                '--quiet[Suppress summary output]' \\
                '-q[Suppress summary output]' \\
                '--progress[Print each file as parsed]' \\
                '--help[Show help]'
            ;;
        info)
            _arguments \\
                ':cpg_file:_files -g "*.json"' \\
                '--json[Output as JSON]' \\
                '--help[Show help]'
            ;;
        query)
            _arguments \\
                ':cpg_file:_files -g "*.json"' \\
                '--kind[Filter by node kind]:kind:(module class function parameter variable call literal return import branch loop block)' \\
                '-k[Filter by node kind]:kind:(module class function parameter variable call literal return import branch loop block)' \\
                '--name[Filter by name regex]:pattern:' \\
                '-n[Filter by name regex]:pattern:' \\
                '--file[Filter by file path substring]:path:' \\
                '-f[Filter by file path substring]:path:' \\
                '--json[Output as JSON]' \\
                '--limit[Max results]:number:' \\
                '-l[Max results]:number:' \\
                '--help[Show help]'
            ;;
        taint)
            _arguments \\
                ':cpg_file:_files -g "*.json"' \\
                '--policy[Policy YAML file]:file:_files -g "*.yaml *.yml"' \\
                '-p[Policy YAML file]:file:_files -g "*.yaml *.yml"' \\
                '-o[Output file]:file:_files' \\
                '--output[Output file]:file:_files' \\
                '--show-sanitized[Include sanitized paths]' \\
                '--json[Output as JSON]' \\
                '--apply[Write annotations back to CPG]' \\
                '--help[Show help]'
            ;;
        viz)
            _arguments \\
                ':cpg_file:_files -g "*.json"' \\
                '-o[Output HTML file]:file:_files -g "*.html"' \\
                '--output[Output HTML file]:file:_files -g "*.html"' \\
                '--title[Visualization title]:title:' \\
                '--open[Open in browser]' \\
                '--help[Show help]'
            ;;
        dot)
            _arguments \\
                ':cpg_file:_files -g "*.json"' \\
                '-o[Output DOT file]:file:_files -g "*.dot"' \\
                '--output[Output DOT file]:file:_files -g "*.dot"' \\
                '--edge-kind[Filter edge kinds]:kind:(contains has_parameter has_return_type flows_to branches_to data_flows_to defined_by used_by calls resolves_to imports)' \\
                '--node-kind[Filter node kinds]:kind:(module class function parameter variable call literal return import branch loop block)' \\
                '--help[Show help]'
            ;;
        config)
            _arguments \\
                '--show[Display effective config]' \\
                '--init[Create .treeloom.yaml in cwd]' \\
                '--set[Set a config key]:key:' \\
                '--unset[Remove a config key]:key:' \\
                '--global[Operate on user config]' \\
                '--help[Show help]'
            ;;
        annotate)
            _arguments \\
                ':cpg_file:_files -g "*.json"' \\
                '--rules[Rules YAML file]:file:_files -g "*.yaml *.yml"' \\
                '-r[Rules YAML file]:file:_files -g "*.yaml *.yml"' \\
                '-o[Output file]:file:_files -g "*.json"' \\
                '--output[Output file]:file:_files -g "*.json"' \\
                '--json[Output summary as JSON]' \\
                '--help[Show help]'
            ;;
        diff)
            _arguments \\
                ':before:_files -g "*.json"' \\
                ':after:_files -g "*.json"' \\
                '--json[Output as JSON]' \\
                '--help[Show help]'
            ;;
        subgraph)
            _arguments \\
                ':cpg_file:_files -g "*.json"' \\
                '-o[Output JSON file]:file:_files -g "*.json"' \\
                '--output[Output JSON file]:file:_files -g "*.json"' \\
                '--depth[Maximum BFS depth]:number:' \\
                '--root[Exact NodeId string]:node_id:' \\
                '--function[FUNCTION node name]:name:' \\
                '--class[CLASS node name]:name:' \\
                '--file[MODULE node file path]:path:' \\
                '--help[Show help]'
            ;;
        pattern)
            _arguments \\
                ':cpg_file:_files -g "*.json"' \\
                '--kind[Node kind for step]:kind:(module class function parameter variable call literal return import branch loop block)' \\
                '--name[Name regex for step]:pattern:' \\
                '--annotation[Annotation key=value]:annotation:' \\
                '--edge-kind[Restrict traversal edge kind]:kind:(contains has_parameter has_return_type flows_to branches_to data_flows_to defined_by used_by calls resolves_to imports)' \\
                '--depth[Maximum wildcard depth]:number:' \\
                '--json[Output as JSON]' \\
                '--help[Show help]'
            ;;
        completions)
            _arguments \\
                ':shell:(bash zsh fish)' \\
                '--help[Show help]'
            ;;
    esac
}

compdef _treeloom treeloom
"""

_FISH_SCRIPT = """\
# treeloom fish completion
# Place this file at ~/.config/fish/completions/treeloom.fish

# Helper: true when no subcommand has been given yet
function __treeloom_no_subcommand
    set -l cmd (commandline -opc)
    for c in build info query taint viz dot config annotate diff subgraph pattern completions
        if contains -- $c $cmd
            return 1
        end
    end
    return 0
end

# Global options (available before any subcommand)
complete -c treeloom -n '__treeloom_no_subcommand' -l version -d 'Show version and exit'
complete -c treeloom -n '__treeloom_no_subcommand' -l verbose -s v -d 'Enable debug logging'
complete -c treeloom -n '__treeloom_no_subcommand' -l json-errors -d 'Output errors as JSON to stderr'

# Subcommands
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'build' -d 'Build a CPG from source files'
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'info' -d 'Display CPG summary statistics'
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'query' -d 'Search and filter CPG nodes'
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'taint' -d 'Run taint analysis on a CPG'
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'viz' -d 'Generate interactive HTML visualization'
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'dot' -d 'Export CPG to Graphviz DOT format'
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'config' -d 'View or modify configuration'
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'annotate' -d 'Apply YAML annotation rules to a CPG'
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'diff' -d 'Compare two CPGs and report structural changes'
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'subgraph' -d 'Extract a subgraph rooted at a specific node'
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'pattern' -d 'Match chain patterns against the CPG'
complete -c treeloom -n '__treeloom_no_subcommand' -f -a 'completions' -d 'Print shell completion script to stdout'

# build
complete -c treeloom -n '__fish_seen_subcommand_from build' -s o -l output -d 'Output JSON file' -F
complete -c treeloom -n '__fish_seen_subcommand_from build' -l exclude -d 'Exclusion glob pattern' -r
complete -c treeloom -n '__fish_seen_subcommand_from build' -l quiet -s q -d 'Suppress summary output'
complete -c treeloom -n '__fish_seen_subcommand_from build' -l progress -d 'Print each file as parsed'

# info
complete -c treeloom -n '__fish_seen_subcommand_from info' -l json -d 'Output as JSON'

# query
complete -c treeloom -n '__fish_seen_subcommand_from query' -l kind -s k -d 'Filter by node kind' -r
complete -c treeloom -n '__fish_seen_subcommand_from query' -l name -s n -d 'Filter by name regex' -r
complete -c treeloom -n '__fish_seen_subcommand_from query' -l file -s f -d 'Filter by file path' -r
complete -c treeloom -n '__fish_seen_subcommand_from query' -l json -d 'Output as JSON'
complete -c treeloom -n '__fish_seen_subcommand_from query' -l limit -s l -d 'Max results' -r

# taint
complete -c treeloom -n '__fish_seen_subcommand_from taint' -l policy -s p -d 'Policy YAML file' -F
complete -c treeloom -n '__fish_seen_subcommand_from taint' -s o -l output -d 'Output file' -F
complete -c treeloom -n '__fish_seen_subcommand_from taint' -l show-sanitized -d 'Include sanitized paths'
complete -c treeloom -n '__fish_seen_subcommand_from taint' -l json -d 'Output as JSON'
complete -c treeloom -n '__fish_seen_subcommand_from taint' -l apply -d 'Write annotations back to CPG'

# viz
complete -c treeloom -n '__fish_seen_subcommand_from viz' -s o -l output -d 'Output HTML file' -F
complete -c treeloom -n '__fish_seen_subcommand_from viz' -l title -d 'Visualization title' -r
complete -c treeloom -n '__fish_seen_subcommand_from viz' -l open -d 'Open in browser'

# dot
complete -c treeloom -n '__fish_seen_subcommand_from dot' -s o -l output -d 'Output DOT file' -F
complete -c treeloom -n '__fish_seen_subcommand_from dot' -l edge-kind -d 'Filter edge kinds' -r
complete -c treeloom -n '__fish_seen_subcommand_from dot' -l node-kind -d 'Filter node kinds' -r

# config
complete -c treeloom -n '__fish_seen_subcommand_from config' -l show -d 'Display effective config'
complete -c treeloom -n '__fish_seen_subcommand_from config' -l init -d 'Create .treeloom.yaml in cwd'
complete -c treeloom -n '__fish_seen_subcommand_from config' -l set -d 'Set a config key' -r
complete -c treeloom -n '__fish_seen_subcommand_from config' -l unset -d 'Remove a config key' -r
complete -c treeloom -n '__fish_seen_subcommand_from config' -l global -d 'Operate on user config'

# annotate
complete -c treeloom -n '__fish_seen_subcommand_from annotate' -l rules -s r -d 'Rules YAML file' -F
complete -c treeloom -n '__fish_seen_subcommand_from annotate' -s o -l output -d 'Output JSON file' -F
complete -c treeloom -n '__fish_seen_subcommand_from annotate' -l json -d 'Output summary as JSON'

# diff
complete -c treeloom -n '__fish_seen_subcommand_from diff' -l json -d 'Output as JSON'

# subgraph
complete -c treeloom -n '__fish_seen_subcommand_from subgraph' -s o -l output -d 'Output JSON file' -F
complete -c treeloom -n '__fish_seen_subcommand_from subgraph' -l depth -d 'Maximum BFS depth' -r
complete -c treeloom -n '__fish_seen_subcommand_from subgraph' -l root -d 'Exact NodeId string' -r
complete -c treeloom -n '__fish_seen_subcommand_from subgraph' -l function -d 'FUNCTION node name' -r
complete -c treeloom -n '__fish_seen_subcommand_from subgraph' -l class -d 'CLASS node name' -r
complete -c treeloom -n '__fish_seen_subcommand_from subgraph' -l file -d 'MODULE node file path' -r

# pattern
complete -c treeloom -n '__fish_seen_subcommand_from pattern' -l kind -d 'Node kind for step' -r
complete -c treeloom -n '__fish_seen_subcommand_from pattern' -l name -d 'Name regex for step' -r
complete -c treeloom -n '__fish_seen_subcommand_from pattern' -l annotation -d 'Annotation key=value' -r
complete -c treeloom -n '__fish_seen_subcommand_from pattern' -l edge-kind -d 'Restrict traversal edge kind' -r
complete -c treeloom -n '__fish_seen_subcommand_from pattern' -l depth -d 'Maximum wildcard depth' -r
complete -c treeloom -n '__fish_seen_subcommand_from pattern' -l json -d 'Output as JSON'

# completions
complete -c treeloom -n '__fish_seen_subcommand_from completions' -f -a 'bash zsh fish' -d 'Shell name'
"""

_SCRIPTS: dict[str, str] = {
    "bash": _BASH_SCRIPT,
    "zsh": _ZSH_SCRIPT,
    "fish": _FISH_SCRIPT,
}

_VALID_SHELLS = tuple(_SCRIPTS)


def register(subparsers: Any) -> None:
    """Register the ``completions`` subcommand."""
    parser: ArgumentParser = subparsers.add_parser(
        "completions",
        help="Print shell completion script to stdout",
    )
    parser.add_argument(
        "shell",
        choices=_VALID_SHELLS,
        help="Target shell: bash, zsh, or fish",
    )
    parser.set_defaults(func=run_cmd)


def run_cmd(args: Namespace, _cfg: object = None) -> int:
    """Execute the completions subcommand."""
    shell: str = args.shell
    script = _SCRIPTS.get(shell)
    if script is None:
        # argparse choices validation should prevent this, but be defensive.
        print(
            f"Error: unsupported shell '{shell}'. Choose from: {', '.join(_VALID_SHELLS)}",
            file=sys.stderr,
        )
        return 1
    sys.stdout.write(script)
    return 0
