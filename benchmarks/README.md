# treeloom benchmarks

Performance benchmarks for CPG construction, taint analysis, serialization, and query operations.

## Setup

```bash
pip install -e ".[bench,languages]"
```

## Running benchmarks

Run all benchmarks with timing output:

```bash
pytest benchmarks/ --benchmark-only
```

Run a specific benchmark file:

```bash
pytest benchmarks/test_build.py --benchmark-only
pytest benchmarks/test_taint.py --benchmark-only
```

Run memory tests (these don't use pytest-benchmark, so omit `--benchmark-only`):

```bash
pytest benchmarks/test_memory.py -v -s
```

## Comparing runs

Save a baseline, then compare after making changes:

```bash
# Save baseline
pytest benchmarks/ --benchmark-only --benchmark-save=baseline

# Run again after your change
pytest benchmarks/ --benchmark-only --benchmark-compare=baseline
```

## Benchmarking against real codebases

Clone a target project, then point `CPGBuilder` at it:

```python
from pathlib import Path
from treeloom import CPGBuilder

cpg = CPGBuilder().add_directory(Path("path/to/requests")).build()
print(f"nodes={cpg.node_count} edges={cpg.edge_count}")
```

Example targets:

| Project   | Approx LOC | Clone URL                                    |
|-----------|-----------|----------------------------------------------|
| requests  | ~6 k      | https://github.com/psf/requests              |
| Flask     | ~15 k     | https://github.com/pallets/flask             |
| Django    | ~350 k    | https://github.com/django/django             |

## Benchmark descriptions

| File                     | What it measures                                        |
|--------------------------|---------------------------------------------------------|
| `test_build.py`          | CPG construction at small / medium / large source sizes |
| `test_taint.py`          | Taint analysis on pre-built small and medium CPGs       |
| `test_serialization.py`  | JSON and dict round-trip at medium CPG size             |
| `test_query.py`          | Node iteration, path finding, and reachability queries  |
| `test_memory.py`         | RSS growth during build and taint (500 MB ceiling)      |
