# VAmPI Analysis Notes

## Target

VAmPI — intentionally vulnerable Flask API at `../unsanitary-code-examples/VAmPI/`.
Contains deliberate SQLi, broken auth, IDOR, mass assignment, and user/password enumeration bugs.

## Initial Build (Before Fixes)

```
Built CPG: 863 nodes, 1645 edges, 11 files
```

## Taint Analysis (Before Fixes): 4 paths

All 4 paths traced the SQL injection in `user_model.get_user()`:
- `username` parameter → f-string interpolation → `user_query` variable → `text()` call → `db.session.execute()` call

The visitor was not emitting DFG edges for keyword arguments or **kwargs splats, and
decorated function definitions were not being visited at all, which caused all Flask
route functions to be invisible in the graph.

---

## Gaps Identified

### 1. `decorated_definition` not in `_NODE_HANDLERS`

Flask route functions are defined as:
```python
@app.route('/api/users/<username>', methods=['GET'])
def get_user(username):
    ...
```

Tree-sitter wraps this in a `decorated_definition` node. The visitor had no handler for
this node type, so it fell through to the generic "recurse into children" path — which
happened to visit the inner `function_definition` correctly, but the decorator call
`app.route(...)` was never visited, and decorator names were never stored in function attrs.

**Fix**: Added `_visit_decorated_definition` handler. It:
- Collects decorator names and visits decorator calls as CPG CALL nodes
- Stores decorator names in `ctx.pending_decorators`
- Visits the inner function/class definition, which reads `pending_decorators` and passes
  them to `emit_function` as `attrs["decorators"]`
- Added `decorators: list[str] | None = None` parameter to `emit_function` (builder and protocol)

### 2. `keyword_argument` returned `None` from `_visit_expression`

Calls like:
```python
User(username=request_data['username'], password=request_data['password'])
```

In tree-sitter, each `name=value` pair in an `argument_list` is a `keyword_argument` node.
The visitor iterated named children of the argument list and called `_visit_expression` on each.
`keyword_argument` fell through to the generic fallback, which recursed into named children
(visiting the value expression) but returned `None`. So `arg_ids[i]` was `None` and no
`DATA_FLOWS_TO` edge was created from the kwarg value to the call.

**Fix**: Added a `keyword_argument` case to `_visit_expression` that extracts the `value`
field and returns `_visit_expression(value)`.

### 3. `dictionary_splat` returned `None` from `_visit_expression`

Calls like:
```python
User(**request_data)
```

The `**request_data` argument is a `dictionary_splat` node. Same issue as keyword_argument —
it fell through to the generic fallback, which visited the inner `identifier` child but
returned `None`, dropping the DFG edge.

**Fix**: Added a `dictionary_splat` case that finds the named `identifier` child and returns
`ctx.defined_vars.get(var_name)`.

### 4. Comprehensions not visited

Calls inside list/set/dict comprehensions and generator expressions were missed:
```python
return [User.json(user) for user in User.query.all()]
```

`list_comprehension` was not handled and fell through to the generic fallback, which does not
recurse deeply enough to find the `call` nodes inside `for_in_clause`.

**Fix**: Added handlers for `list_comprehension`, `set_comprehension`, `generator_expression`,
and `dictionary_comprehension`. Each visits the iterable expression in `for_in_clause`
and the element expression(s).

---

## After Fixes

```
Built CPG: 919 nodes, 1866 edges, 11 files
```

Taint paths: **4 → 40** (10x increase)

New paths found include:

- HTTP input from `request.get_json()` flowing through `request_data.get('username')` into
  `User.query.filter_by()` / `Book.query.filter_by()` — these were missed before because
  `request_data.get('username')` is a call result used as a **keyword argument** to `filter_by`.

- JWT token extracted from `request.headers.get('Authorization')` flowing through
  `token_validator()` → `resp` dict → `resp['sub']` subscript → `User.query.filter_by()`.
  This traces the broken authentication / IDOR pattern (attacker controls auth header content).

- Route parameters (e.g., `book_title` in `get_by_title(book_title)`) flowing through
  `str(book_title)` → `Book.query.filter_by()`. These functions were previously invisible
  because they are decorated with `@vuln_app.route(...)`.

- `username` parameter in `delete_user()` flowing to `User.query.filter_by().delete()` —
  another IDOR (admin can delete arbitrary users, but the path still shows unsanitized
  route input reaching the delete operation).

---

## Remaining Gaps

### Route parameter → body not yet taint-sourced via HTTP

The taint policy uses `PARAMETER` nodes as `user_input` sources, which correctly catches
route parameters. However, `request.get_json()` subscript access (e.g. `request_data['key']`)
does not appear as an HTTP source unless the subscript resolves to the `request.get_json()`
call via DFG. This works now for `.get()` calls (recognized by the `http_input` source regex
`request.*get`), but subscript access `request_data['key']` is currently tracked as
`user_input` only if `request_data` was already a parameter. The `http_input` source should
also match subscript nodes whose root is a `request.get_json()` call — this is a policy
concern, not a visitor gap.

### Mass assignment not detected as a distinct vulnerability class

The pattern:
```python
user = User(username=request_data['username'], password=request_data['password'],
            email=request_data['email'], admin=request_data['admin'])
```

Is now correctly traced (HTTP input → kwarg → User constructor). However, the *mass
assignment* variant:
```python
if vuln and 'admin' in request_data:
    user = User(**request_data)
```

Is now traced via the `dictionary_splat` fix (`request_data` → `User` call). Whether this
reaches a "sink" depends on policy; the User constructor itself is not a sink in the current
policy. A consumer (sanicode) would need to annotate the `User` constructor as a
mass-assignment sink to surface this.

### No decorator-based route URL tracking

Decorator names are now stored in `attrs["decorators"]`. However, the URL path string
(e.g., `'/api/users/<username>'`) is not extracted and stored. This would be useful for
sanicode to correlate findings with API routes. Future enhancement: parse route URL and
HTTP method out of `@app.route(...)` decorator attrs.

### `try/except` body not fully visited in some paths

Some statements inside `try` blocks may not be fully visited if they appear in tree-sitter
`try_statement` nodes. The current visitor recurses generically into unrecognized nodes, so
most cases work. A dedicated `try_statement` handler could improve reliability.

---

## Test Results

```
79 passed  (tests/lang/test_python.py — up from 70)
837 passed (full suite)
ruff: all checks passed
```
