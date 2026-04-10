# CLI Reference

All commands are accessed via the `treeloom` entry point. Most commands operate on a CPG JSON file produced by `treeloom build`.

---

## Global Flags

These flags are accepted by every subcommand.

| Flag | Description |
|------|-------------|
| `--version` | Print treeloom version and exit. |
| `-v`, `--verbose` | Enable debug logging. |
| `--json-errors` | Emit error messages as JSON objects on stderr instead of human-readable text. Useful for programmatic callers. |

---

## Build & Watch

### `build`

Parse source files and produce a CPG JSON file.

```
treeloom build PATH [OPTIONS]
```

`PATH` may be a file or a directory. When a directory is given, treeloom recurses into it and parses all files whose extension matches a registered language visitor.

| Flag | Description |
|------|-------------|
| `-o`, `--output FILE` | Write CPG JSON to `FILE`. Defaults to `cpg.json` in the current directory. Use `-` to write to stdout. |
| `--exclude PATTERN` | Gitignore-style glob to exclude from directory traversal. Repeatable. Defaults include `**/__pycache__`, `**/node_modules`, `**/.git`, `**/venv`, `**/.venv`. |
| `-q`, `--quiet` | Suppress all output except errors. |
| `--progress` | Print phase progress updates (Parse, CFG, Call resolution, Inter-procedural DFG). |
| `--language LANG` | Force a specific language visitor regardless of file extension. Useful for files with non-standard extensions. |
| `--timeout SECONDS` | Abort the build if it exceeds this wall-clock time. Raises an error with a partial result message. |
| `--include-source` | Store `source_text` for each node in `attrs`. Increases output size significantly; useful for visualization or downstream tools that need source snippets. |

Examples:

```bash
# Build from a directory
treeloom build src/ -o cpg.json --progress

# Build a single file
treeloom build main.py -o main.cpg.json

# Exclude test directories and write to stdout
treeloom build . --exclude "tests/**" --exclude "**/*.test.js" -o -
```

---

### `watch`

Watch a directory for file changes and automatically rebuild the CPG on each change.

```
treeloom watch PATH [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `-o`, `--output FILE` | Write CPG JSON to `FILE`. Defaults to `cpg.json`. |
| `--interval SECONDS` | Polling interval in seconds. Default: `1.0`. |
| `--exclude PATTERN` | Gitignore-style glob to exclude. Repeatable. Same defaults as `build`. |
| `-q`, `--quiet` | Suppress rebuild notifications; only print errors. |

Example:

```bash
treeloom watch src/ -o cpg.json --interval 2
```

---

## Inspect

### `info`

Print summary statistics for a CPG file.

```
treeloom info CPG_FILE [OPTIONS]
```

Outputs node counts by kind, edge counts by kind, number of source files, and treeloom version used to produce the file.

| Flag | Description |
|------|-------------|
| `--json` | Emit stats as a JSON object instead of human-readable text. |

Example:

```bash
treeloom info cpg.json
treeloom info cpg.json --json | jq '.nodes.function'
```

---

### `query`

Search nodes in the CPG by kind, name, file, scope, or annotation.

```
treeloom query CPG_FILE [OPTIONS]
```

All filter flags are ANDed together — a node must match all specified filters to appear in results.

| Flag | Description |
|------|-------------|
| `--kind KIND` | Filter by node kind (`function`, `call`, `variable`, `class`, `parameter`, `literal`, `import`, `return`, `branch`, `loop`, `block`, `module`). |
| `--name PATTERN` | Filter by node name. Interpreted as a Python regex (`re.search`). |
| `--file PATH` | Filter to nodes in a specific source file. Accepts a path substring match. |
| `--scope NODE_ID` | Filter to nodes whose scope is the given node ID. |
| `--annotation KEY` | Filter to nodes that have this annotation key set. |
| `--annotation-value VALUE` | When combined with `--annotation`, filter to nodes where the annotation equals this value (string comparison). |
| `--count` | Print only the count of matching nodes, not the nodes themselves. |
| `--limit N` | Return at most N results. Default: 100. |
| `--output-format FORMAT` | `table` (default), `json`, or `ids` (one node ID per line). |
| `--json` | Alias for `--output-format json`. |

Examples:

```bash
# List all functions
treeloom query cpg.json --kind function

# Find call sites whose name matches exec or eval
treeloom query cpg.json --kind call --name "exec|eval"

# Find nodes annotated as sinks
treeloom query cpg.json --annotation role --annotation-value sink

# Count variables in a specific file
treeloom query cpg.json --kind variable --file "src/auth.py" --count
```

---

### `edges`

Query edges in the CPG by kind, source, or target node.

```
treeloom edges CPG_FILE [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--kind KIND` | Filter by edge kind (`contains`, `calls`, `data_flows_to`, `flows_to`, `branches_to`, `defined_by`, `used_by`, `resolves_to`, `imports`, `has_parameter`, `has_return_type`). |
| `--source NODE_ID` | Filter to edges whose source node ID equals this value. |
| `--target NODE_ID` | Filter to edges whose target node ID equals this value. |
| `--limit N` | Return at most N results. Default: 100. |
| `--count` | Print only the count of matching edges. |
| `--output-format FORMAT` | `table` (default), `json`, or `pairs` (one `source -> target` per line). |
| `--json` | Alias for `--output-format json`. |

Examples:

```bash
# Show all call graph edges
treeloom edges cpg.json --kind calls

# Show all edges leaving a specific node
treeloom edges cpg.json --source "function:src/app.py:10:0:1"

# Count data flow edges
treeloom edges cpg.json --kind data_flows_to --count
```

---

## Analysis

### `taint`

Run taint analysis on a CPG using a policy file.

```
treeloom taint CPG_FILE --policy POLICY_FILE [OPTIONS]
```

The policy file is a Python module that defines a `make_policy(cpg)` function returning a `TaintPolicy`. See the [Sanicode Integration Guide](sanicode-integration.md) for policy authoring details.

| Flag | Description |
|------|-------------|
| `--policy FILE` | **Required.** Path to the Python policy module. |
| `--show-sanitized` | Include sanitized paths in output. By default, only unsanitized paths are shown. |
| `--json` | Emit results as a JSON array of taint paths. |
| `--apply FILE` | Write a new CPG JSON with taint annotations applied to each reached node. |
| `-o`, `--output FILE` | Write taint results to `FILE` instead of stdout. |

Examples:

```bash
# Run taint and show unsanitized paths
treeloom taint cpg.json --policy my_policy.py

# Include sanitized paths and output as JSON
treeloom taint cpg.json --policy my_policy.py --show-sanitized --json -o taint.json

# Annotate the CPG with taint results and save
treeloom taint cpg.json --policy my_policy.py --apply annotated.json
```

---

### `pattern`

Match node chains using a pattern defined in a Python snippet or file.

```
treeloom pattern CPG_FILE --pattern PATTERN_FILE [OPTIONS]
```

The pattern file is a Python module that defines a `make_pattern()` function returning a `ChainPattern`. See `treeloom.query.pattern` for the `ChainPattern` and `StepMatcher` API.

| Flag | Description |
|------|-------------|
| `--pattern FILE` | **Required.** Path to the Python pattern module. |
| `--json` | Emit matched chains as JSON. |
| `--limit N` | Return at most N matched chains. Default: 50. |

Example:

```bash
treeloom pattern cpg.json --pattern param_to_exec.py --limit 20
```

---

### `annotate`

Apply annotation rules from a rules file to nodes in the CPG.

```
treeloom annotate CPG_FILE --rules RULES_FILE [OPTIONS]
```

The rules file is a Python module defining a `make_rules()` function that returns a list of `(predicate, key, value)` tuples. For each node where `predicate(node)` is true, `annotate_node(node.id, key, value)` is called.

| Flag | Description |
|------|-------------|
| `--rules FILE` | **Required.** Path to the Python rules module. |
| `-o`, `--output FILE` | Write the annotated CPG JSON to `FILE`. Defaults to overwriting the input file. |
| `--json` | Print a summary of applied annotations as JSON instead of writing a file. |

Example:

```bash
treeloom annotate cpg.json --rules security_rules.py -o annotated.json
```

---

## Extract

### `subgraph`

Extract a subgraph rooted at a specific node, function, class, or file.

```
treeloom subgraph CPG_FILE [OPTIONS] -o OUTPUT_FILE
```

Exactly one of `--root`, `--function`, `--class`, or `--file` must be provided.

| Flag | Description |
|------|-------------|
| `--root NODE_ID` | Root node ID to expand from. |
| `--function NAME` | Use the first FUNCTION node matching `NAME` as root. Regex accepted. |
| `--class NAME` | Use the first CLASS node matching `NAME` as root. Regex accepted. |
| `--file PATH` | Include all nodes in the given source file. |
| `--depth N` | Maximum BFS depth from the root. Default: 10. |
| `-o`, `--output FILE` | **Required.** Write the subgraph CPG JSON to `FILE`. |

Examples:

```bash
# Extract everything reachable from a function within 5 hops
treeloom subgraph cpg.json --function "handle_request" --depth 5 -o subgraph.json

# Extract all nodes in one file
treeloom subgraph cpg.json --file "src/auth.py" -o auth_subgraph.json
```

---

### `diff`

Compare two CPG files and report structural differences.

```
treeloom diff CPG_FILE_A CPG_FILE_B [OPTIONS]
```

Reports nodes and edges that appear in one graph but not the other, grouped by kind. Useful for tracking how the graph changes between builds (e.g., after a refactor or during CI).

| Flag | Description |
|------|-------------|
| `--json` | Emit diff as a JSON object with `added_nodes`, `removed_nodes`, `added_edges`, `removed_edges`. |
| `--strip-prefix PREFIX` | Strip a path prefix from file paths before comparison, so graphs built from different root directories can be compared. |
| `--match-by-full-path` | When matching nodes between graphs, require exact file path equality rather than filename-only matching. Default is filename-only. |

Example:

```bash
treeloom diff cpg-before.json cpg-after.json --json | jq '.added_nodes | length'
```

---

## Export

### `viz`

Generate an interactive HTML visualization of the CPG.

```
treeloom viz CPG_FILE [OPTIONS]
```

Produces a self-contained HTML file using Cytoscape.js with layer toggles (Structure, Data Flow, Control Flow, Call Graph), click-to-inspect panels, node search, and zoom/pan.

| Flag | Description |
|------|-------------|
| `--title TITLE` | Title shown in the browser tab and page header. Default: `"Code Property Graph"`. |
| `--open` | Open the output file in the default browser immediately after writing. |
| `--exclude-kind KIND` | Exclude nodes of this kind from the visualization. Repeatable. |
| `-o`, `--output FILE` | Write HTML to `FILE`. Default: `cpg.html`. |

Examples:

```bash
# Generate and open immediately
treeloom viz cpg.json --open

# Save with a title, exclude literals (less visual noise)
treeloom viz cpg.json --title "auth module" --exclude-kind literal -o auth.html
```

---

### `dot`

Export the CPG to Graphviz DOT format.

```
treeloom dot CPG_FILE [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--edge-kind KIND` | Include only edges of this kind. Repeatable. When omitted, all edge kinds are included. |
| `--node-kind KIND` | Include only nodes of this kind. Repeatable. When omitted, all node kinds are included. |
| `-o`, `--output FILE` | Write DOT to `FILE`. Default: stdout. |

Examples:

```bash
# Export the full graph
treeloom dot cpg.json -o full.dot

# Export only the call graph
treeloom dot cpg.json --edge-kind calls -o callgraph.dot

# Render directly
treeloom dot cpg.json | dot -Tsvg -o graph.svg
```

---

## Server

### `serve`

Expose the CPG as an HTTP JSON API. Useful for integrating treeloom into editors, CI pipelines, or web dashboards without spawning a new process per query.

```
treeloom serve CPG_FILE [OPTIONS]
```

Endpoints mirror the CLI query surface: `GET /nodes`, `GET /edges`, `GET /info`, `POST /query`, etc. See `GET /` for the full route list once the server is running.

| Flag | Description |
|------|-------------|
| `--host HOST` | Bind address. Default: `127.0.0.1`. |
| `--port PORT` | Port number. Default: `7410`. |

Example:

```bash
treeloom serve cpg.json --port 8080
# Then: curl http://localhost:8080/nodes?kind=function
```

---

## Configuration

### `config`

View or modify treeloom's configuration. Settings are stored in `~/.config/treeloom/config.toml` by default.

```
treeloom config [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--show` | Print the current configuration and its source file path. |
| `--init` | Write a default configuration file if one does not already exist. |
| `--set KEY VALUE` | Set a configuration key to a value. Example: `--set default_output cpg.json`. |
| `--unset KEY` | Remove a configuration key, reverting it to the default. |
| `--global` | Apply `--set`/`--unset` to the global config file rather than the project-local one (`.treeloom.toml` in the current directory). |

Examples:

```bash
# View current config
treeloom config --show

# Set a project-local default output path
treeloom config --set default_output build/cpg.json

# Set a global default timeout
treeloom config --global --set timeout 120
```

---

### `completions`

Generate shell completion scripts.

```
treeloom completions SHELL
```

`SHELL` must be one of `bash`, `zsh`, or `fish`.

Examples:

```bash
# Bash
treeloom completions bash >> ~/.bashrc

# Zsh
treeloom completions zsh > ~/.zfunc/_treeloom
# Then add `fpath=(~/.zfunc $fpath)` and `autoload -U compinit && compinit` to ~/.zshrc

# Fish
treeloom completions fish > ~/.config/fish/completions/treeloom.fish
```
