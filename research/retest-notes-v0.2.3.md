# treeloom Retest: v0.2.1 vs v0.2.3

Tested against: vulpy (vulnerable Python Flask app) at
`/Users/wjackson/Developer/unsanitary-code-examples/vulpy/bad/`

Test date: 2026-03-25
treeloom version: current `main` branch
Previous test: testing-notes-v0.2.1.md (commit 78304a9, v0.2.1-era)

---

## Before vs After (Quantitative)

### Build Metrics

| Metric | v0.2.1 | v0.2.3 | Change |
|--------|--------|--------|--------|
| Files parsed | 21 (of 41 attempted) | 18 (only .py) | Fixed: only parses requested language |
| Nodes | 659 | 905 | +37% |
| Edges | 987 | 1796 | +82% |

### Edge Counts by Kind

| Edge Kind | v0.2.1 | v0.2.3 | Change |
|-----------|--------|--------|--------|
| contains | 631 | 858 | +227 |
| data_flows_to | 180 | 358 | +178 (+99%) |
| flows_to | 0 | 349 | **+349 (new!)** |
| defined_by | 86 | 92 | +6 |
| used_by | 47 | 51 | +4 |
| calls | 31 | 31 | unchanged |
| has_parameter | 12 | 29 | +17 |
| branches_to | 0 | 28 | **+28 (new!)** |

The two most impactful changes: CFG edges (flows_to, branches_to) went from
zero to 377, and data_flows_to nearly doubled.

### Taint Analysis

| Metric | v0.2.1 | v0.2.3 | Change |
|--------|--------|--------|--------|
| Taint paths found | 0 | 27 | **+27** |
| Nodes annotated | ~40 (rules matched) | 75 | +35 |
| Sources identified | 0 effective | 13 | +13 |
| Sinks identified | 0 effective | 8 | +8 |

### Pattern Matching

| Pattern | v0.2.1 | v0.2.3 | Change |
|---------|--------|--------|--------|
| SQLi (param -> c.execute) | 0 via data_flows_to | 12 chains | **Working** |
| Format injection (param -> .format) | 0 | 8 chains | **Working** |

---

## New CLI Features Tested

### Working Correctly

**`treeloom edges` (issue #42).** Edge query works well. All three edge kinds
tested (data_flows_to, calls, flows_to) returned meaningful results with proper
formatting. The `--limit` flag works. The output format (Kind / Source / Target)
is clean and readable. This was the #7 recommendation from the first test.

**`--scope` filter on query (issue #43).** `--kind call --scope login` returned
exactly the 6 calls inside the `login` function in libuser.py. This was #10
on the recommendation list.

**`--count` filter on query (issue #44).** Returns a single integer, perfect
for scripting. 41 functions, 258 calls, 62 imports. This was not on the
original list but was implied by the "pipe through wc -l" complaint.

**`--annotation` / `--annotation-value` query (issue #45).** After `--apply`,
querying for `tainted=True` returned 50 annotated nodes. Querying for
`taint_role=sink` returned 8 sinks, `taint_role=source` returned 13 sources.
This was recommendation #9 from the first test (annotation query).

**`--match-by-basename` on diff (issue #41).** The diff output now correctly
matches files by basename across different directories. `libuser.py` shows as
a changed file with node count delta (+87), not as removed+added. New files,
removed files, changed files, and function-level changes are all correctly
reported. This was recommendation #4.

**`--json-errors` (issue #46).** Errors now output structured JSON:
`{"error": "file_not_found", "message": "...", "path": "..."}`. This was
recommendation #5.

**`--language` filter on build (issue #49).** `--language python` correctly
restricts parsing to .py files only. The build progress now shows only 18 files
instead of 41. This was recommendation #8.

**DOT `--edge-kind` pruning (issue #48).** The pruned DOT (data_flows_to only)
is 875 lines vs 2706 for the full graph -- a 68% reduction. This was
recommendation #9 (DOT node filtering).

**Viz `--exclude-kind`.** Excluding imports and literals reduced the HTML from
1.2MB to 791KB. The graph is more focused on structurally interesting nodes.

**Subgraph + taint preservation.** Extracting the `login` function subgraph
(19 nodes, 46 edges) preserved taint annotations. Querying
`--annotation tainted` on the subgraph returned 6 tainted nodes including the
SQLi chain (username -> format -> c.execute -> fetchone).

### No Issues Found

All tested features worked on the first try. No crashes, no unexpected output.

---

## Remaining Gaps

**Inter-procedural DFG is partial.** The 31 CALLS edges exist and some
inter-procedural data flow works (the taint engine found paths from
`libapi.py:8` through `libuser.login` to `c.execute`). However, `request.form.get`
in Flask route handlers (mod_user.py) is only partially tracked -- 4
`request.form.get` calls show up as taint sources, but the connection from
those calls through variable assignment to cross-module sinks could be stronger.

**No `request.form` -> variable assignment DFG.** While `request.form.get` is now
identified as a taint source (good!), the data flow from the call result
through variable assignment to the function call argument is not always
complete. The taint engine compensates by marking broad patterns, but a more
precise DFG would reduce false positives in larger codebases.

**No field sensitivity.** `obj.field` is not tracked separately from `obj`.
This is documented as aspirational in CLAUDE.md. For vulpy this doesn't matter
much, but for larger apps with complex object graphs it will.

**No `--output-format` on query.** Still no CSV/TSV output for piping into
other tools. Low priority but noted in the original test.

---

## Overall Assessment

treeloom has gone from **non-functional for security analysis** to **genuinely useful**.

The v0.2.1 test found zero taint paths in a codebase with 3 known SQL injection
vulnerabilities. The conclusion was that treeloom could not detect the most
common injection pattern in Python. That conclusion is now invalid.

v0.2.3 finds 27 taint paths, 12 SQLi pattern chains, and 8 format-injection
chains. The three critical fixes (string formatting DFG, CFG edges,
inter-procedural DFG) addressed the top 3 recommendations from the first test.
The 7 CLI improvements (edges command, scope filter, count filter, annotation
query, basename diff, json-errors, language filter) addressed 7 of the
remaining 10 recommendations.

The pattern matching results are particularly encouraging. The SQLi pattern
correctly identifies all three vulnerable functions (login at line 5, create at
line 20, password_change at line 46) with both username and password parameters
flowing to c.execute. The format-injection pattern adds the .format() calls
themselves as sinks, catching the URL format injection in api_list.py and the
path traversal in libapi.py that the SQLi pattern misses.

The subgraph extraction preserving taint annotations means a security agent can
extract a focused view of a single function, see exactly which nodes are
tainted, and generate findings without processing the full graph. This is the
workflow sanicode needs.

Score: treeloom is now capable of serving as the CPG backend for sanicode's
security analysis pipeline against real-world Python applications.
