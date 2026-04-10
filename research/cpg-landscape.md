# treeloom — Landscape Analysis and Rationale

This document covers the Code Property Graph (CPG) tooling landscape and explains the decision to build treeloom rather than adopt an existing platform. It is aimed at developers familiar with static analysis who might reasonably ask "why not just use Joern?" or "why not CodeQL?"

---

## Code Property Graph Platforms

### Joern

**Repository:** github.com/joernio/joern
**Language:** Scala (JVM)
**Supported languages:** C/C++, Java, Python, JavaScript/TypeScript, Kotlin, PHP, Ruby, LLVM bitcode

Joern is the most mature open-source CPG platform available. It implements the full unified CPG model: AST, CFG, PDG, and call graph combined into a single property graph, queryable via a Scala-based DSL (`cpg.method.name("foo").calledBy(...)`) or via Cypher after Neo4j export.

It originated as a vulnerability research tool (Fabian Yamaguchi's 2014 dissertation) and has accumulated significant capability over a decade: inter-procedural analysis, type recovery, and a growing set of pre-built security scanners. The query language is expressive and the community is active.

The fundamental problem for our stack is the JVM runtime. Joern requires Java 17+ and ships as a multi-hundred-megabyte distribution. In an air-gapped OpenShift environment with UBI9 base images, the JVM is not a permitted dependency — it would add a second supply chain, significant image bloat, and introduces FIPS compliance questions around the JVM's cryptographic providers. Running Joern as an out-of-process service and consuming its output over an API trades one problem for another: now you have a required sidecar, a translation layer between Joern's graph model and your own, and you've effectively outsourced the graph schema to an upstream project.

**Verdict:** Correct architecture, wrong runtime.

---

### Fraunhofer AISEC CPG

**Repository:** github.com/Fraunhofer-AISEC/cpg
**Language:** Kotlin/JVM
**Supported languages:** C/C++, Java, Python, Go, Ruby, LLVM-IR

Fraunhofer AISEC's CPG library is research-oriented and takes a similar unified graph approach to Joern. It is arguably better structured as a library (intended to be embedded in analysis tooling) rather than as a standalone scanner. The Python and Go frontends are notable.

The constraints are identical to Joern: JVM runtime, Kotlin build system, no Python library interface. If anything, as a research project it receives less community attention than Joern and has a higher risk of API instability.

**Verdict:** Same architecture constraints as Joern, less ecosystem support.

---

### CodeQL

**URL:** codeql.github.com
**Supported languages:** C/C++, C#, Go, Java/Kotlin, JavaScript/TypeScript, Python, Ruby, Swift

CodeQL uses a relational database model: the source code is compiled into a snapshot database, then queried with QL, a logic-programming language with SQL-like syntax. Queries express dataflow paths in terms of source/sink relations, and the engine handles the inter-procedural reasoning.

For open-source projects on GitHub, CodeQL is excellent. The query packs are well-maintained, the ecosystem is mature, and GitHub's infrastructure handles the heavy lifting.

The hard disqualifier is deployment model: CodeQL requires GitHub infrastructure (github.com or GHES) for the database extraction and query execution pipeline in practice. While there is a CodeQL CLI, self-hosting a full offline pipeline is not a supported use case, and the licensing terms for the standalone CLI restrict commercial use of the query packs. For an air-gapped OpenShift environment with no egress, CodeQL is not a viable option.

**Verdict:** Excellent for GitHub-hosted projects; not self-hostable for air-gapped deployments.

---

## Codebase Knowledge Graph Tools

These tools focus on building navigable knowledge graphs from code, often for LLM-assisted development rather than security analysis.

### Code-Graph-RAG

**Repository:** github.com/vitali87/code-graph-rag
**Backend:** tree-sitter + KuzuDB or FalkorDB

A demonstration project showing how to build a code graph queryable via natural language. Uses tree-sitter for parsing, stores entities and relationships in KuzuDB or FalkorDB, and routes queries through an LLM. The graph model is entity-relationship (files, functions, calls, imports) rather than a full CPG — there is no CFG, no dataflow edges, no taint propagation.

Interesting as a proof of concept for the embedding + graph RAG pattern. Not a foundation for security analysis.

### GitNexus

**Backend:** KuzuDB, 4-pass AST pipeline

GitNexus builds interactive knowledge graphs from repositories. Its 4-pass pipeline progressively enriches the graph: file structure → symbol extraction → cross-reference resolution → dependency analysis. The focus is developer navigation and understanding, not vulnerability analysis.

### GraphGen4Code

**Repository:** github.com/wala/graph4code
**Affiliation:** IBM Research
**Backend:** WALA (Java), RDF output

IBM Research's graph generation toolchain built on WALA. Generates RDF graphs from Python code (despite the JVM dependency, it targets Python via WALA's Python frontend). The output is an RDF triple store queryable with SPARQL. Designed for program understanding and API usage mining tasks, not security analysis. Requires WALA, which is a JVM dependency.

### FalkorDB Code Graph

**Repository:** github.com/FalkorDB/code-graph
**Backend:** Neo4j-compatible graph, tree-sitter parsing

FalkorDB's code graph tool converts GitHub repositories into a property graph. It is oriented around repository navigation and is actively developed. The graph model covers files, functions, classes, and call relationships. Like the other tools in this category, there is no CFG or dataflow analysis.

### CodePrism

**Repository:** github.com/rustic-ai/codeprism
**Languages:** Rust, Python, JavaScript/TypeScript, Java
**Interface:** MCP server

CodePrism is the most relevant tool in this category for our use case. It is Python-friendly, exposes an MCP server interface, and covers the languages we care about. The analysis depth is navigational: symbol resolution, call graphs, import graphs. It does not construct CFGs or perform dataflow/taint analysis.

It is worth watching. If CodePrism adds dataflow analysis, the calculus changes. As of now, it provides the graph substrate but not the analysis layer treeloom needs to exist.

---

## Static Analysis Frameworks

### WALA

**Repository:** github.com/wala/WALA
**Affiliation:** IBM Research
**Languages:** Java, Android, JavaScript

WALA is a comprehensive Java program analysis library: pointer analysis, call graph construction, interprocedural dataflow, program slicing. It is used as the foundation for several other tools (including GraphGen4Code). WALA is a JVM library with no Python bindings, and its JavaScript support is secondary. Not applicable to our Python-native stack.

### Soot / SootUp

**Repository:** github.com/soot-oss/soot
**Languages:** Java bytecode

Soot is the canonical Java bytecode analysis framework. Multiple intermediate representations (Jimple, Shimple), call graph construction (CHA, RTA, VTA, points-to), and dataflow analysis support. SootUp is a modernized rewrite with better API design.

Like WALA, Soot is JVM-only and Java-focused. Not applicable here.

### tree-sitter-graph

**Repository:** github.com/tree-sitter/tree-sitter-graph
**Languages:** 100+ (any language with a tree-sitter grammar)

tree-sitter-graph provides a DSL for constructing graphs from tree-sitter parse trees. It is a building block: you write graph construction rules in the DSL, and it produces a graph from the parsed AST. What it does not provide is call graph construction, control flow analysis, dataflow propagation, or taint tracking. It gives you the scaffold for building a graph — the analytical content must come from elsewhere.

treeloom uses tree-sitter as its parsing layer (for the same reason tree-sitter-graph does: broad language coverage, fast, battle-tested). treeloom provides what tree-sitter-graph leaves to the consumer.

---

## Graph Database Backends

A brief note on the graph database options, since backend choice affects deployment constraints:

**Neo4j** is the most established option with the richest ecosystem (Cypher, GDS library, browser UI). Its community edition has licensing restrictions that complicate redistribution. Running Neo4j as a required sidecar contradicts our offline-native, single-process deployment model.

**KuzuDB** is an embedded, in-process graph database with Cypher support. No separate server process, fast analytical queries, Python bindings that work well. This is the right backend for treeloom: zero infrastructure requirements, ships as a Python package, performant for the graph sizes we encounter in typical codebases.

**FalkorDB** is Neo4j-compatible and lighter weight, but still requires a running server process.

**ArangoDB** is a multi-model database (document + graph) that supports AQL. The multi-model flexibility is not useful for our narrow use case, and it similarly requires a running server.

treeloom uses KuzuDB for in-process operation and NetworkX for the in-memory working graph during analysis passes, exporting to KuzuDB for persistence and complex queries.

---

## Why Build treeloom

The tools above are not obscure or poorly-maintained. Joern in particular is excellent at what it does. The decision to build treeloom is driven by concrete constraints, not "not invented here."

### JVM dependency

Joern, WALA, Soot, and Fraunhofer AISEC CPG all require a JVM. Our deployment target is air-gapped OpenShift with UBI9 Python base images. Introducing a JVM means:

- A second package manager and supply chain (Maven/Gradle artifacts), distinct from our Python packaging.
- Significantly larger container images. A minimal UBI9 Python image is ~200MB. Adding OpenJDK 17 adds another ~200-300MB.
- FIPS compliance complexity. RHEL's OpenJDK ships FIPS-compliant providers, but validating JVM FIPS configuration is a separate audit scope from the Python stack.
- Container startup latency. JVM initialization is measurable; for a CLI tool expected to be fast, this matters.

None of these are insurmountable, but all of them are real costs with no corresponding benefit, since we need a Python library interface in any case.

### Integration cost

Even if we were willing to carry a JVM, using Joern as a library means writing a Python-to-JVM bridge (via Py4J, JPype, or a subprocess/gRPC interface). That bridge becomes an abstraction layer we must maintain, version against Joern's API, and test for correctness of the translation.

At that point we are doing the hard work (building and maintaining a CPG interface) without controlling the underlying representation. When Joern's graph schema changes — and it does, as Joern has evolved substantially over its lifetime — our bridge breaks.

### Taint policy coupling

Joern has its own source/sink/sanitizer definition format. sanicode maintains taint policy as a separate concern (consumer-provided source/sink/sanitizer sets, per-scan configuration). Mapping sanicode's policy format to Joern's TaintPass configuration, and mapping Joern's finding output back to sanicode's finding schema, is ongoing translation work that grows with every policy update.

treeloom's design inverts this: the CPG layer is policy-agnostic. treeloom provides the graph and the traversal API. sanicode provides source sets, sink sets, and sanitizer sets at query time. No translation layer, no schema mismatch.

### Offline-native constraint

Joern's distribution (the `joern-cli` bundle) is approximately 500MB before any languages are downloaded. It references Maven Central for some toolchain components. In an air-gapped environment, you either pre-mirror everything required or you discover missing artifacts at runtime. The Python ecosystem, by contrast, ships as self-contained wheels; `pip install treeloom` in an air-gapped environment with a local PyPI mirror works without additional infrastructure.

### CodeQL is specifically out

CodeQL's licensing model and its tight coupling to GitHub infrastructure (the `codeql database create` command invokes GitHub-hosted compilers and extractors for most languages in the practical workflow) make it unsuitable for self-hosted air-gapped deployments. This is not a criticism of CodeQL — it is excellent within its intended use case — but the use case does not match ours.

### tree-sitter-graph is a building block, not a solution

tree-sitter-graph solves the parsing and graph construction layer cleanly. It does not construct call graphs, does not compute control flow, does not propagate dataflow, and has no taint analysis capability. It is a prerequisite technology, not an alternative to treeloom.

treeloom uses tree-sitter (via the Python `tree-sitter` package) for parsing and AST construction. tree-sitter-graph the DSL tool is not used, since treeloom constructs its graph programmatically from tree-sitter ASTs in Python.

### Consumer control over the graph API

sanicode has a specific contract it needs from its CPG layer:

- Annotate nodes with source/sink/sanitizer classification from externally-provided policy.
- Return taint paths as structured objects (not query result sets), suitable for LLM prompt construction.
- Support overlay visualization: annotate a subgraph with finding context for display.
- Efficient subgraph extraction by entry point or by sink type.
- NetworkX-compatible export for the in-process analysis loop.

Adapting an existing tool's output format to this contract requires understanding the tool's internal graph schema deeply enough to write correct and maintainable translation code. The translation is more complex than the CPG construction itself, because CPG construction is a well-defined problem (parse → extract nodes → resolve edges) while translation is inherently lossy and tied to both schemas simultaneously.

Building the graph layer in Python, with this contract as the design input, produces a cleaner result than adapting Joern's output.

### What treeloom adopts from Joern

The conceptual model is correct, and treeloom adopts it: a unified graph combining AST structure, control flow edges, and dataflow edges, queryable as a single property graph. This is Yamaguchi et al.'s core insight, and it is the right abstraction for vulnerability analysis.

treeloom does not reimagine the CPG model. It implements the CPG model in a Python-native, offline-capable, policy-agnostic way that fits the deployment and integration constraints of the sanicode stack.

---

## Summary

| Tool | Runtime | Taint Analysis | Air-gap capable | Python library | Verdict |
|---|---|---|---|---|---|
| Joern | JVM | Yes, inter-proc | Yes (large) | No | Wrong runtime |
| Fraunhofer CPG | JVM | Yes | Yes (large) | No | Wrong runtime |
| CodeQL | JVM + GitHub | Yes, inter-proc | No | No | Wrong model |
| Code-Graph-RAG | Python | No | Yes | Yes | No dataflow |
| CodePrism | Python | No | Yes | Yes | No dataflow |
| tree-sitter-graph | Rust/Python | No | Yes | Partial | Building block only |
| treeloom | Python | Yes | Yes | Yes | Fits constraints |

The gap is narrow but real: there is no Python-native, offline-capable CPG library with dataflow/taint analysis. treeloom fills it.
