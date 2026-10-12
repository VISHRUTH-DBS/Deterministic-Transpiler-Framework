# Deterministic Transpiler Framework

Four source-to-source translators built from the same three-phase pipeline —
**Lexer → Parser → Code Generator** — with no machine learning, no probabilistic
matching, no network access and no third-party dependencies (Python 3.10+ standard library only).
Same input, same output, every run.

| Pair key    | Translation                | The compiler problem it demonstrates                              |
|-------------|----------------------------|-------------------------------------------------------------------|
| `py2js`     | Python → JavaScript        | Indentation-based scoping → brace-delimited blocks; scope analysis |
| `ts2js`     | TypeScript → JavaScript    | Type erasure: removing type-level nodes from an AST                |
| `md2html`   | Markdown → HTML            | Linear markers → nested tags (block structure + delimiter stack)   |
| `json2yaml` | JSON → YAML                | Bracket/comma structure → indentation; scalar-quoting rules        |

---

## 1. Architecture

```
transpiler/
├── core.py            Token, RegexLexer, TokenStream (peek/expect/mark/reset), CodeWriter, TranspileError
├── engine.py          Pair registry + CLI
├── python_to_js/      lexer.py  ast_nodes.py  parser.py  analysis.py  generator.py
├── ts_to_js/          lexer.py  ts_ast.py  type_parser.py  parser.py  eraser.py  printer.py
├── md_to_html/        lexer.py  md_ast.py  block_parser.py  inline_parser.py  generator.py
├── json_to_yaml/      lexer.py  json_ast.py  parser.py  generator.py
└── tests/test_transpilers.py
```

Every pair is a package exposing `transpile(source: str) -> str`. Phases communicate only
through data: the lexer returns a list of tokens, the parser returns an immutable (frozen
dataclass) AST, the generator returns text. A phase never reaches into another's internals,
so any one can be replaced or tested alone. `core.py` is the only shared code.

### How each phase's responsibility shifts

| Phase | Structured code (Python, TypeScript) | Data / markup (JSON, Markdown) |
|---|---|---|
| **Lexer** | **Python:** a line-oriented state machine owns an *indent stack* and bracket depth and synthesises `INDENT`/`DEDENT`/`NEWLINE` tokens — whitespace *is* syntax. Regexes handle the content of each line. **TypeScript:** pure regex lexing; whitespace is discarded. The key decision is to emit `>` as a single token so `Array<Array<number>>` is not read as `>>`; the parser re-joins adjacent `>` into `>>`, `>=` only in operator position. | **JSON:** a flat, context-free regex token set (RFC 8259 strict). **Markdown:** a *line classifier* with two states (normal / inside a code fence). Meaning depends on line start, so tokens are whole lines (heading, quote, list item, text...), not words. Inline syntax is deliberately *not* lexed here — it is context-sensitive. |
| **Parser** | Precedence-climbing expression grammar plus statement grammar; a handful of semantic checks (`return` outside a function, `break` outside a loop). **TypeScript** additionally parses a full *type grammar* into real nodes and uses bounded speculation (`mark`/`reset`) for the genuinely ambiguous cases: generic call `f<T>(x)` vs. `a < b`, and arrow functions vs. parenthesised expressions. | **JSON:** a 20-line recursive descent; the only extra rule is rejecting duplicate keys (YAML cannot represent them). **Markdown** has *two* parsers: a block parser where containers (quotes, list items) collect their lines, strip their prefix and **recurse** (nesting depth = recursion depth), and an inline parser: one left-to-right scan plus a **delimiter stack** that resolves `*`/`_` runs into nested emphasis. |
| **Generator** | **Python → JS** is more than printing: it must *add* syntax the source lacks (`let` declarations) and preserve Python semantics where JS differs (floor `//`, sign-of-divisor `%`, chained comparisons, loop-bound evaluation). Output uses precedence-driven parenthesisation. **TypeScript → JS** runs an AST→AST **eraser pass** first, then a printer that *refuses* any surviving type-level node. | **YAML** generation is a pure layout problem: nesting depth becomes indentation, and the hard part is **scalar quoting** — a string that would be re-read as a bool, number, date or null must be quoted. **HTML** generation is a tree walk with escaping, tight/loose list layout, and URL-scheme filtering. |

### Design notes worth knowing

* **Py→JS scope analysis** (`python_to_js/analysis.py`). Python has function scope and no
  declarations; JS `let` is block scoped. For each scope the generator decides per variable:
  emit `let x = ...` at the first assignment when every use of `x` lies inside that block at/after
  it; otherwise hoist a single `let x;` to the top of the scope. Loop variables use `for (let i ...)`
  unless read outside their loops.
* **Loop bounds.** `range(n)` bounds are evaluated once in Python. If the bound is not provably
  loop-invariant (e.g. `len(xs)` while the body appends), it is hoisted into `const __stopN`.
* **Type erasure** (`ts_to_js/eraser.py`) does two things: *drops* nodes that only the type checker
  needs (interfaces, aliases, `declare`, overload signatures, `import type`) and *unwraps/blanks*
  wrappers and slots (`x as T`, `x!`, annotations, generics, `?`, `this` parameters).
* **Errors** are `TranspileError(message, line, col)`; the CLI prints `error: message (line L, col C)`
  and exits 1.

---

## 2. Supported subsets

**Python:** `=` and augmented assignment (`+= -= *= /= //= %= **=`); `+ - * / // % **`; comparisons incl. chains;
`and or not`; `if/elif/else`, `while`, `for x in range(a[, b[, literal-step]])`, `for x in iterable`;
`def` / `return`; `break continue pass`; lists, subscripts (`a[-1]` → `.at(-1)`), method calls; strings; `print len abs min max str int float`.

**TypeScript:** `let/const/var` with annotations, functions (generics, optional/default/rest params, overload signatures),
arrow functions, function expressions, `if/while/for/for-of/for-in`, `interface`, `type`, `declare`, `import` (incl. type-only),
`export` on declarations, `as`/`satisfies`/`!`, object/array literals, template literals (passed through verbatim),
optional chaining `a?.b`, `new`, full operator set.

**Markdown:** ATX headings, paragraphs, hard/soft breaks, `*em*` `**strong**` `_em_` `` `code` ``, links, images, autolinks,
fenced code, block quotes, nested bullet/ordered lists (tight and loose), thematic breaks, backslash escapes. Raw HTML is escaped, and
`javascript:`/`vbscript:`/`data:` URLs are neutralised.

**JSON → YAML:** all of RFC 8259; output is block-style YAML with 2-space indentation.

Anything outside a subset raises a `TranspileError` naming the construct; nothing is silently mistranslated.

---

## 3. Test cases (exact input → exact output)

All four live in `tests/test_transpilers.py` (`ExactOutputTests`).

### 3.1 Python → JavaScript

```python
def factorial(n):
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result

total = 0
count = 10
while count > 0:
    if count % 2 == 0:
        total += count
    elif count == 5:
        total -= 1
    else:
        pass
    count -= 1

print("total:", total, factorial(5), 7 // 2, 2 ** 10)
```

```js
function __mod(a, b) {
  return ((a % b) + b) % b;
}

function factorial(n) {
  let result = 1;
  for (let i = 2; i < n + 1; i++) {
    result *= i;
  }
  return result;
}

let total = 0;
let count = 10;
while (count > 0) {
  if (__mod(count, 2) === 0) {
    total += count;
  } else if (count === 5) {
    total -= 1;
  }
  count -= 1;
}
console.log("total:", total, factorial(5), Math.floor(7 / 2), 2 ** 10);
```

`%` becomes the `__mod` helper because Python's result takes the divisor's sign (`-7 % 3 == 2`) while JS's takes the dividend's (`-1`).
`//` becomes `Math.floor(a / b)`; the empty `else: pass` is dropped.

### 3.2 TypeScript → JavaScript

```ts
import type { Shape } from "./shapes";
import { area, type Unit } from "./util";

interface Point {
  x: number;
  y?: number;
}

type Id = string | number;

function scale<T extends number>(value: T, factor: number = 2): number {
  return (value as number) * factor;
}

const origin: Point = { x: 0, y: 0 };
let total: number = 0;
for (let i: number = 0; i < 5; i++) {
  total += scale<number>(i);
}
const label = (document.title as string)!.trim();
const double = <T,>(n: number): number => n * 2;
```

```js
import { area } from "./util";

function scale(value, factor = 2) {
  return value * factor;
}

const origin = { x: 0, y: 0 };
let total = 0;
for (let i = 0; i < 5; i++) {
  total += scale(i);
}
const label = document.title.trim();
const double = (n) => n * 2;
```

### 3.3 Markdown → HTML

````markdown
# Release **Notes**

Welcome to *the* `v2` release. See [docs](https://example.com "Docs") & more.

- Faster parser
- Nested items:
  - one
  - two
- Done

1. Install
2. Run

> Tip: use `--fast`.

```js
if (a < b) run();
```
````

```html
<h1>Release <strong>Notes</strong></h1>
<p>Welcome to <em>the</em> <code>v2</code> release. See <a href="https://example.com" title="Docs">docs</a> &amp; more.</p>
<ul>
<li>Faster parser</li>
<li>Nested items:
<ul>
<li>one</li>
<li>two</li>
</ul>
</li>
<li>Done</li>
</ul>
<ol>
<li>Install</li>
<li>Run</li>
</ol>
<blockquote>
<p>Tip: use <code>--fast</code>.</p>
</blockquote>
<pre><code class="language-js">if (a &lt; b) run();
</code></pre>
```

### 3.4 JSON → YAML

```json
{"name":"demo","version":1.0e2,"tags":["a","true","x: y"],"deps":[{"id":1,"ok":true},[1,2],[]],"meta":{"empty":{},"note":null,"text":"line1\nline2"}}
```

```yaml
name: demo
version: 1.0e+2
tags:
  - a
  - "true"
  - "x: y"
deps:
  - id: 1
    ok: true
  - - 1
    - 2
  - []
meta:
  empty: {}
  note: null
  text: "line1\nline2"
```

The strings `"true"` and `"x: y"` are quoted so a YAML parser reads them back as strings; `1.0e2` is normalised to `1.0e+2` so
YAML 1.1 parsers (e.g. PyYAML) read a float rather than a string.

---

## 4. Verification guide

Run everything from the directory that **contains** the `transpiler/` folder:

```bash
# CLI
python -m transpiler --list
python -m transpiler py2js   prog.py                     # file → stdout
python -m transpiler json2yaml data.json -o data.yaml     # file → file
echo '{"a":[1,2]}' | python -m transpiler json2yaml       # stdin

# Library
python -c "from transpiler import transpile; print(transpile('py2js', 'print(1 + 2)\n'))"

# Tests (44)
python -m unittest discover -s transpiler/tests -t . -v
```

The suite has five layers of checking:

1. **Exact output** for the four pairs above, plus about 40 targeted cases (precedence, hoisting, ASI, nested generics, loose lists, quoting).
2. **Error tests** for malformed input, including line/column positions.
3. **Differential execution** (needs `node`): 8 Python programs are run by CPython and, after transpiling, by Node; stdout must match.
   This is what validates `%`, `//`, `**`, chained comparisons and scoping semantics.
4. **Round trip** (needs `PyYAML`): 1,500 seeded-random JSON documents → YAML → `yaml.safe_load` must equal the original.
5. **Reference comparison** (needs `markdown-it-py`) against a CommonMark implementation, and `node --check` on generated JS.
   Layers 3–5 skip automatically if the tool is missing: `pip install pyyaml markdown-it-py`.

---

## 5. Extending the framework

**Add a language construct (the usual loop):**

1. *Lexer* — add a rule to the rules list (`("ARROW", r"=>")`). Order matters: first match wins, so put longer operators first.
2. *AST* — add a frozen dataclass to `*_ast.py` and include it in the relevant `Union`.
3. *Parser* — add a method at the right precedence level or statement position. Use `ts.accept/expect`; use `ts.mark()/reset()` only for genuine ambiguity.
4. *Generator* — add `_stmt_<NodeName>` / `_expr_<NodeName>` (dispatch is by class name, so a missing one fails loudly with `AttributeError`).
5. *Tests* — add an exact-output case; if semantics could differ between languages, add a differential case.

**Worked examples**

* **Python tuple unpacking** `a, b = b, a`: add `TupleTarget`/`TupleLiteral` nodes; in the generator emit `[a, b] = [b, a];` and teach `analysis.py` that both names are assigned.
* **Python `class`** → add `ClassDef(name, bases, body)`; emit `class X extends B { ... }` with `self` → `this`.
* **TypeScript `enum`** (currently rejected): erasure is *not enough* because enums have a runtime form. Add an `EnumDeclaration` node and have the eraser **lower** it to an object literal (a transformation rather than a deletion) — the AST→AST pass is the right place.
* **TypeScript classes**: parameter properties (`constructor(private x: number)`) must be lowered to `this.x = x;` — the same lowering pattern.
* **Markdown tables / setext headings:** add a block token and parser function; add `Table` to `md_ast.py` and a renderer in `generator.py`.
* **New pair** (e.g. CSV → JSON): create a package with the four modules, expose `transpile`, add one `Pair(...)` line in `engine.py`.

**Known limitations (by design of the subset):** comments are discarded (to keep them, attach trivia tokens to AST nodes);
Python truthiness of empty containers, list `+`/`*`, and integers beyond 2⁵³ differ in JavaScript; regex literals and JSX are not lexed in TypeScript;
template-literal substitutions are passed through without erasing types inside them; Markdown raw HTML, tables, setext headings and
indented code blocks are not supported.
