# Language Support

treeloom ships with built-in visitors for eight languages. Grammar packages are optional dependencies — install them via `pip install "treeloom[languages]"` or per-language (e.g., `pip install treeloom-python`). A missing grammar produces a clear `ImportError` rather than a silent failure.

---

## Support Matrix

### File Extensions

| Language   | Extensions                        |
|------------|-----------------------------------|
| Python     | `.py`, `.pyi`                     |
| JavaScript | `.js`, `.mjs`, `.cjs`             |
| TypeScript | `.ts`, `.tsx`                     |
| Go         | `.go`                             |
| Java       | `.java`                           |
| C          | `.c`, `.h`                        |
| C++        | `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh` |
| Rust       | `.rs`                             |

### AST Nodes

| Node kind   | Python | JavaScript | TypeScript | Go | Java | C | C++ | Rust |
|-------------|:------:|:----------:|:----------:|:--:|:----:|:-:|:---:|:----:|
| MODULE      | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| CLASS       | yes    | yes        | yes        | yes (struct/interface) | yes | no | yes (struct/class) | yes (struct/impl) |
| FUNCTION    | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| PARAMETER   | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| VARIABLE    | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| CALL        | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| LITERAL     | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| IMPORT      | yes    | yes        | yes        | yes | yes (include as import) | yes (include as import) | yes (include as import) | yes (use/extern crate) |
| RETURN      | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| BRANCH      | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| LOOP        | yes    | yes        | yes        | yes | yes | yes | yes | yes |

### Control Flow

| Construct        | Python | JavaScript | TypeScript | Go | Java | C | C++ | Rust |
|-----------------|:------:|:----------:|:----------:|:--:|:----:|:-:|:---:|:----:|
| if/elif/else    | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| for loop        | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| while loop      | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| switch/match    | yes (match) | yes   | yes        | yes | yes | yes | yes | yes (match) |
| try/catch       | BRANCH | BRANCH     | BRANCH     | no  | yes    | no | BRANCH | no |

`try/catch` constructs are emitted as BRANCH nodes in some languages. Java visits try/catch/finally bodies and emits caught exception variables but does not create BRANCH nodes. Languages without checked exceptions (Go, C, Rust) don't model them.

### Data Flow

| Capability              | Python | JavaScript | TypeScript | Go | Java | C | C++ | Rust |
|------------------------|:------:|:----------:|:----------:|:--:|:----:|:-:|:---:|:----:|
| Assignment tracking     | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| Parameter tracking      | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| Return value tracking   | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| Augmented assignment    | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| Destructure/unpack      | yes    | yes        | yes        | yes (multi-return) | no | no | no | yes (let bindings) |
| Type annotations in DFG | yes    | no         | yes        | yes | yes | no | no  | yes |

### Call Resolution

| Strategy                | Python | JavaScript | TypeScript | Go | Java | C | C++ | Rust |
|------------------------|:------:|:----------:|:----------:|:--:|:----:|:-:|:---:|:----:|
| Name-based             | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| Qualifier stripping    | yes    | yes        | yes        | yes | yes | no | no | no |
| Type-based / MRO       | yes    | no         | no         | no | yes | no | no | no |
| Import-following       | yes    | no         | no         | no | yes | no | no | no |
| Interface dispatch     | no     | no         | no         | no | no | no | no | no |

### Source Text Spans

| Feature         | Python | JavaScript | TypeScript | Go | Java | C | C++ | Rust |
|----------------|:------:|:----------:|:----------:|:--:|:----:|:-:|:---:|:----:|
| start_location  | yes    | yes        | yes        | yes | yes | yes | yes | yes |
| end_location    | yes    | no         | no         | no | yes | no | no | no |
| source_text     | yes    | no         | no         | no | yes | no | no | no |

`end_location` and `source_text` are stored in `CpgNode.attrs` when populated. Additional languages will gain these fields in future releases.

---

## Language Notes

### Python

The reference implementation. Python and Java share the most complete feature set, including type-based MRO resolution and import-following call resolution, where a `from module import func` import causes treeloom to search the original module scope when resolving calls to `func`. Type annotations are extracted from three sources — parameter annotations (`def foo(x: Dog):`), variable annotations (`x: Dog = ...`), and function return types (`def foo() -> Dog:`) — to populate the type map used for method call resolution. Generic type parameters are stripped (`list[str]` → `list`), and explicit annotations take priority over constructor inference. Async functions (`async def`) are handled as FUNCTION nodes with `is_async=True` in `attrs`. Match statements (`match`/`case`, Python 3.10+) are modeled as BRANCH nodes.

### JavaScript

Handles ES modules (`import`/`export`) and CommonJS (`require`/`module.exports`). Arrow functions, function expressions, and class methods are all emitted as FUNCTION nodes. Dynamic `require()` calls are emitted as CALL nodes but are not resolved to function definitions. Template literals are emitted as LITERAL nodes.

### TypeScript

Builds on the JavaScript visitor. Type annotations are extracted from parameter and variable declarations and stored in `attrs["type_annotation"]`. Generic type parameters are captured but not resolved — they appear in the type annotation string as written in source. Interface declarations are emitted as CLASS nodes with `attrs["is_interface"] = True`. Decorator syntax is captured on FUNCTION and CLASS nodes.

### Go

Go has no classes; structs and interfaces are emitted as CLASS nodes. Methods are FUNCTION nodes with `attrs["receiver"]` set to the receiver type name. Multi-return functions are supported: when a function has multiple return types, each return position is tracked separately as a RETURN node attribute. Package-level variable declarations are emitted as VARIABLE nodes scoped to the MODULE.

### Java

At feature parity with the Python visitor. Class hierarchies (`extends`, `implements`) are captured on CLASS nodes via `attrs["bases"]`. Lambda expressions are emitted as FUNCTION nodes with synthetic names (e.g., `lambda$4$8`) and their parameters as PARAMETER nodes. Record declarations are emitted as CLASS nodes with record components as PARAMETER nodes. Switch statements (including arrow-syntax rules), try/catch/finally, try-with-resources, do-while loops, throw statements, static initializer blocks, and synchronized blocks are all handled. Field declarations emit VARIABLE nodes visible to method bodies. Varargs parameters (`Object... args`) are emitted as PARAMETER nodes with type annotation `Object...`. The visitor tracks `inferred_type` on variables from declared types and constructor calls, and passes `receiver_inferred_type` on method calls for type-based MRO resolution and import-following — matching the Python visitor's call resolution capabilities.

### C

Struct and union definitions are emitted as CLASS nodes. Typedef'd names are captured in `attrs`. Function pointer variables are emitted as VARIABLE nodes with `attrs["is_function_pointer"] = True`. Preprocessor `#include` directives are emitted as IMPORT nodes; macro calls are emitted as CALL nodes. Macro expansions are not resolved — macro CALL nodes remain unresolved in the call graph.

### C++

Inherits C behavior and adds class support (including multiple inheritance, captured in `attrs["extends"]`). Template definitions are emitted but template parameters are not tracked individually. Operator overloads are emitted as FUNCTION nodes with the operator as the name (e.g., `operator+`). Lambda expressions are emitted as FUNCTION nodes with synthetic names. Constructors and destructors are FUNCTION nodes named after the class with `attrs["is_constructor"]`/`attrs["is_destructor"]`.

### Rust

Struct, enum, and trait definitions are emitted as CLASS nodes. Trait implementations (`impl Trait for Type`) create FUNCTION nodes scoped to the impl block, with `attrs["trait_impl"]` recording the trait name. Closures are emitted as FUNCTION nodes with synthetic names. `use` declarations are emitted as IMPORT nodes. Lifetime annotations and generic bounds are captured as strings in `attrs` but are not analyzed structurally.

---

## Known Limitations

**Call resolution is best-effort for all languages.** treeloom does not implement a type inference engine. For any language, if a call cannot be resolved to a definition by name or import tracing, the CALL node remains in the graph without a CALLS edge. This is by design — unresolved calls are visible orphans, not silent gaps.

**Only Python and Java have MRO-based and import-following resolution.** For all other languages, call resolution is name-based with qualifier stripping. This means method calls on typed objects (`obj.method()`) that cannot be resolved by name alone will remain unresolved.

**Only Python and Java populate `end_location` and `source_text`.** These fields in `CpgNode.attrs` are blank for all other languages. Code that reads these fields should guard with `attrs.get("source_text")` rather than assuming presence.

**Cross-language call resolution works via shared function nodes.** When a TypeScript file calls a function defined in a JavaScript file, the TypeScript visitor's `resolve_calls` sees all FUNCTION nodes regardless of source language — because `CPGBuilder` passes the full function list to each visitor's `resolve_calls`. This means TS→JS resolution works if the function name is unambiguous.

**Grammar packages are optional dependencies.** If the grammar for a language is not installed, parsing files in that language raises a clear `ImportError` with an install command. The error is per-file — other languages in the same build continue normally.

**Parse errors are non-fatal.** Files whose tree-sitter parse tree contains errors (`root_node.has_error`) are skipped with a warning. The build continues with the remaining files.
