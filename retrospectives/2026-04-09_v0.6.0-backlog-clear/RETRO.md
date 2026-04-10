# Retrospective: v0.6.0 Backlog Clear

**Date:** 2026-04-09
**Effort:** Clear entire open backlog (5 issues), cut v0.6.0 release
**Issues:** #65, #67, #68, #69, #74
**Commits:** 3a4d2dd..bcdb483 (4 feature/doc commits + release)

## What We Set Out To Do

Clear all 5 open GitHub issues in priority order:
1. #67 (high) — Per-phase progress and timing for build command
2. #69 (medium) — Pre-filter function index by language in call resolution
3. #68 (medium) — Add --timeout flag to prevent hangs
4. #74 (unset) — Include source text spans in CPG nodes
5. #65 (low) — Create standalone user documentation

Then cut and publish v0.6.0 to PyPI.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| #68 closed without code — already implemented | Scope reduction | Feature existed with tests; stale issue |
| #67 + #69 combined into one commit | Good pivot | Both modify `_resolve_calls()` and `build()` in builder.py |
| MODULE nodes excluded from source_text (#74) | Good pivot | Review caught that storing entire file contents as a node attr was excessive |
| Only Python visitor updated for end_location (#74) | Scope deferral | Other visitors deferred; Java prioritized as #75 |
| Ruff format adoption deferred | Scope deferral | 74-file formatting diff not worth during feature release; CI doesn't enforce it |

## What Went Well

- **Implement + review agent pattern caught real issues every time.** Review of #67/#69 found: dead `funcs_by_ext` variable, missing `_check_timeout` calls, phase numbering gap when registry is None, duplicate inline imports. Review of #74 found: MODULE source_text bloat, protocol surface area note. All fixed before commit.
- **Parallel doc writing.** Four agents wrote getting-started, library guide, taint analysis, and language-support + CLI reference simultaneously. ~2.5 min wall time for 1,794 lines.
- **Catching #68 as already-done** saved a wasted implementation cycle and kept commit history clean.
- **Release process ran cleanly end-to-end.** No CI failures, no version mismatches, PyPI publish succeeded on first try.
- **Taint guide `--models` flag and CLI reference `--verbose` description inaccuracies caught and fixed before commit.**

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| 7 language visitors don't populate `end_location` | Follow-up | Java: #75 (high), others: #76 (medium) |
| No `--include-source` integration test on multi-file fixture | Follow-up | #77 (low) |
| Ruff format drift (74 files) | Accept | CI doesn't enforce it; not causing problems |

## Action Items

- [x] Create issue for Java visitor end_location (#75, priority-high)
- [x] Create issue for remaining 6 visitors (#76, priority-medium)
- [x] Create issue for --include-source integration test (#77, priority-low)

## Patterns

**Start:** Nothing new to start — first retro for this project.

**Continue:**
- Implement + review sub-agent pattern: caught meaningful issues on every pass.
- Parallel doc agents for independent documentation files.
- Checking whether issues are already resolved before implementing.

**Stop:** Nothing identified — session ran smoothly.
