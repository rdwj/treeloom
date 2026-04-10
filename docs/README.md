# treeloom Documentation

treeloom is a language-agnostic Code Property Graph library. For installation and a quick start, see the [root README](../README.md).

## Getting Started

- [Getting Started](getting-started.md) -- installation, building your first CPG, exploring and visualizing the graph.

## Reference

- [CLI Reference](cli-reference.md) -- all 15 subcommands with flags and examples.
- [Language Support](language-support.md) -- support matrix for all 8 built-in language visitors: extensions, AST nodes, control flow, data flow, call resolution, and known limitations.
- [Library Guide](library-guide.md) -- in-depth coverage of the public API: building CPGs, navigating the graph, annotations, queries, pattern matching, and serialization.
- [Taint Analysis Guide](taint-analysis.md) -- how the taint engine works, defining `TaintPolicy`, reading `TaintResult`, custom propagators, stdlib models, `implicit_param_sources`, CLI usage, and a full SQL injection worked example.
- [Sanicode Integration Guide](sanicode-integration.md) -- how to use treeloom as the graph backend for sanicode, including migration from the old KnowledgeGraph, the annotation contract, and taint policy setup.

## API

- [CLAUDE.md](../CLAUDE.md) -- full API specification: data model, method signatures, algorithms, builder pipeline, taint engine, query API, pattern matching, export formats, and overlay system.
- [llms.txt](../llms.txt) -- concise LLM-optimized summary of the API surface and CLI.

## Other directories

- [research/](../research/) -- CPG tooling landscape analysis, testing reports, and investigation notes.
- [benchmarks/](../benchmarks/) -- benchmark suite for build, taint, serialization, query, and memory.
