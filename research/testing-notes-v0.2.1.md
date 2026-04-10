# treeloom CLI Testing Notes

Tested against: vulpy (vulnerable Python Flask app) at
`/Users/wjackson/Developer/unsanitary-code-examples/vulpy/bad/`

Test date: 2026-03-25
treeloom version: current `main` branch (78304a9)

---

## What Worked Well

**Build speed.** Building a 21-file CPG took ~0.3 seconds. Fast enough for
interactive use and watch mode.

**Query command.** The `--kind`, `--name` (regex), and `--file` (substring)
filters compose naturally. The regex name matching was particularly useful for
security review: `--name "execute|cursor|connect"` immediately surfaced all
database interaction. The `--name "format"` query directly revealed the SQL
injection on libuser.py:12 because the call name includes the full expression
(`c.execute("SELECT...".format(username, password)).fetchone`). This is
genuinely more informative than just seeing `c.execute`.

**Info command.** Clean summary with useful breakdowns by node kind, edge kind,
and file extension. JSON output mode works correctly and is
machine-parseable.

**Subgraph extraction.** `--function login` and `--file libuser` both worked
intuitively. The extracted subgraphs were correctly scoped. The
`--function`/`--file`/`--class` convenience flags are much nicer than requiring
raw NodeId strings.

**Annotation rules.** The YAML format is straightforward. The summary output
showing per-rule match counts is helpful for validating rules:
```
rule 1 (kind=PARAMETER, name=username|password|text|otp): 23 matches -> role=entry_point
rule 2 (kind=CALL, name=execute): 17 matches -> role=sink, cwe_id=89
```

**Pattern matching with `contains` edges.** Found all 17 function-to-execute
chains, correctly identifying the vulnerable functions.

**Serve command.** Clean HTTP API. Endpoints return well-structured JSON.
The `/health`, `/info`, `/query` endpoints all work. Announced endpoints and
port clearly on startup.

**Shell completions.** Available for bash, zsh, and fish. Headers include
installation instructions.

**Config command.** `--show` displays effective defaults, `--init` creates a
starter config file. The defaults (exclude patterns for __pycache__, node_modules,
.git, venv) are sensible.


## What Was Hard to Use

**Diff is useless across directories.** `treeloom diff bad.json good.json`
shows all files as "new" and "removed" because the absolute paths differ
(`vulpy/bad/libuser.py` vs `vulpy/good/libuser.py`). There is no
`--strip-prefix` or `--match-by-basename` option. For the primary use case of
comparing before/after versions of the same codebase, this makes diff
non-functional.

**Build progress is misleading.** The progress output shows `[1/41] Parsing
.gitignore...` for files that are silently skipped (no language support). A user
sees 41 files being "parsed" but only 21 end up in the graph. The progress
output should either skip unsupported files or mark them as skipped:
`[1/41] Skipping .gitignore (no language support)`.

**DOT export includes all nodes even with `--edge-kind` filter.** Running
`treeloom dot --edge-kind data_flows_to` produces 1210 lines including every
node in the graph, even nodes with zero data_flows_to edges. The filter should
restrict output to connected nodes only, otherwise the DOT output is
unreadable.

**No way to query edges.** The `query` command only searches nodes. There is no
way to ask "show me all `data_flows_to` edges" or "what edges connect this
node?" An `edges` subcommand or `--edges` flag would be valuable, especially
for debugging DFG construction issues.

**No `--scope` filter on query.** You can filter by `--kind`, `--name`, and
`--file`, but not by scope (e.g., "all calls inside the `login` function").
This would be valuable for focused analysis.

**Verbose mode (`-v`) adds nothing to `info`.** Running `treeloom -v info
cpg.json` produces identical output to running without `-v`. Expected: debug
info about deserialization time, file sizes, annotation counts, etc.

**`--json-errors` flag has no effect.** Both `treeloom info nonexistent.json`
and `treeloom --json-errors info nonexistent.json` produce the same plain-text
error. The flag is documented but not implemented.


## What Was Missing

**Taint analysis cannot trace through string formatting.** This is the single
biggest gap. The `data_flows_to` edges do not connect function parameters to
`.format()` calls or `%`-style string interpolation. In vulpy, the primary
vulnerability is:

```python
def login(username, password):
    ...
    user = c.execute(
        "SELECT * FROM users WHERE username = '{}' and password = '{}'".format(username, password)
    ).fetchone()
```

The parameters `username` and `password` flow into `.format()`, producing a
tainted string that flows into `c.execute()`. Taint analysis found **zero
paths**. This means treeloom cannot detect the most common SQL injection
pattern in Python.

**No CFG edges.** The `info` command shows zero `flows_to` or `branches_to`
edges. The CFG layer is either not implemented or not working for Python. This
limits analysis to AST structure and the (incomplete) DFG.

**No `request.form` tracking.** Flask's `request.form.get('username')` calls
are detected as CALL nodes but there is no data flow connecting them to the
variables they are assigned to in the Flask route handlers. An agent cannot
trace from HTTP input to vulnerable sink.

**No cross-function data flow.** The `CALLS` edges exist (31 of them), but
there is no inter-procedural data flow. When `mod_user.py` calls
`libuser.login(username, password)`, there is no `data_flows_to` edge from the
arguments at the call site to the parameters of the target function.

**No `--output-format` on query.** Query supports `--json` but not CSV, TSV,
or other formats that would be useful for piping into other tools.

**No "edges from/to node" query.** Given a node ID, there is no CLI way to see
its incoming and outgoing edges. The serve command has `/node/<id>` but the CLI
lacks an equivalent.

**No `--language` filter on build.** You cannot say "only parse Python files."
The build command processes every supported file type it finds, including
JavaScript payloads that are irrelevant to a Python security review.

**No annotation query.** After annotating, there is no way to query "show me
all nodes annotated with role=sink" from the CLI. You have to write a custom
YAML annotation rule to match the same things again.

**No `--count` flag on query.** To get counts you must pipe through `wc -l`
and subtract the header lines, or use `--json` and parse. A `--count` flag
would be more ergonomic.


## False Positives / False Negatives

### Taint Analysis

**100% false negative rate.** Taint analysis found zero paths in a codebase
with at least 3 exploitable SQL injection vulnerabilities:

1. `libuser.py:12` -- `username`/`password` -> `.format()` -> `c.execute()` (classic SQLi)
2. `libuser.py:25` -- `username`/`password` -> `%` formatting -> `c.execute()` (classic SQLi)
3. `libuser.py:53` -- `username`/`password` -> `.format()` -> `c.execute()` (classic SQLi)

Root cause: no `data_flows_to` edges from parameters through string
formatting operations to the execute calls.

### Pattern Matching

**100% false negative rate on data_flows_to patterns.** Both the SQLi pattern
and format-injection pattern found zero matches for the same reason.

**Pattern matching with `contains` edges worked correctly**, finding all 17
function-to-execute chains. However, `contains` patterns cannot distinguish
vulnerable from safe code (they just show structural containment, not data
flow).

### Annotation

**No false positives or negatives.** The rule-based annotation matched exactly
what the rules described. The annotation system itself is working correctly;
the problem is downstream in taint analysis.


## Specific Bug Reports

1. **`--json-errors` flag is not implemented.** The flag is accepted by the
   argument parser but has no effect on error output format. Plain text errors
   are produced regardless.

2. **Build progress counts unsupported files.** The progress shows
   `[1/41] Parsing .gitignore...` but .gitignore is not a supported language.
   The file count (41) includes .png, .xcf, .css, .html, .txt, and .gitignore
   files that cannot be parsed. Only 21 files end up in the graph.

3. **Diff treats files from different directories as completely different.**
   `libuser.py` in `bad/` and `libuser.py` in `good/` are reported as
   removed+added rather than modified, making the diff output useless for the
   primary comparison use case.

4. **DOT `--edge-kind` filter does not filter nodes.** All nodes appear in
   output regardless of whether they participate in edges of the specified kind.

5. **No `data_flows_to` edges through string formatting.** Parameters used in
   `.format()` and `%` string interpolation do not generate data flow edges.
   This is the highest-impact bug because it makes taint analysis unable to
   detect the most common injection patterns.

6. **Zero CFG edges generated.** No `flows_to` or `branches_to` edges appear in
   the built CPG, despite the code containing if/else branches and loops.


## Recommendations

Ordered by impact on the security review use case:

1. **Fix DFG through string operations (critical).** `.format()` args and `%`
   interpolation vars must generate `data_flows_to` edges to the resulting
   string/call. Without this, taint analysis is non-functional for real-world
   Python injection detection. This is the single most important improvement.

2. **Implement CFG edges (high).** `flows_to` and `branches_to` edges are
   described in the architecture but produce zero edges in practice. These are
   needed for path-sensitive analysis.

3. **Implement inter-procedural data flow (high).** Connect call-site arguments
   to callee parameters via `data_flows_to`. The `CALLS` edges exist but data
   does not flow across them.

4. **Fix diff to match by basename (medium).** Add `--strip-prefix` or
   `--match-by-basename` so files from different directories can be compared.

5. **Implement `--json-errors` (low).** The flag exists but does nothing.
   Machine-parseable errors are important for agent integration.

6. **Filter build progress to supported files only (low).** Either skip
   unsupported files in the progress output or mark them as skipped.

7. **Add edge query capability (medium).** Either a `treeloom edges` command
   or `--edges` flag on query, so users can inspect the graph connectivity.

8. **Add `--language` filter to build (low).** Let users specify which
   languages to include, avoiding irrelevant files.

9. **Filter DOT output nodes by edge kind (low).** When `--edge-kind` is
   specified, only include nodes that participate in edges of that kind.

10. **Add `--scope` filter to query (medium).** Allow filtering nodes by
    enclosing function/class/module to focus analysis on specific code regions.
