"""Exact-output tests for the four translation pairs, plus error and property tests.

Run from the directory that contains the `transpiler/` package:

    python -m unittest discover -s transpiler/tests -t . -v
"""

from __future__ import annotations

import random
import shutil
import subprocess
import unittest

from transpiler import TranspileError, transpile

# ======================================================================= Python -> JS
PY_SOURCE = '''def factorial(n):
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
'''

PY_EXPECTED = '''function __mod(a, b) {
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
'''

# ================================================================== TypeScript -> JS
TS_SOURCE = '''import type { Shape } from "./shapes";
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
'''

TS_EXPECTED = '''import { area } from "./util";

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
'''

# ================================================================== Markdown -> HTML
MD_SOURCE = '''# Release **Notes**

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
'''

MD_EXPECTED = '''<h1>Release <strong>Notes</strong></h1>
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
'''

# ===================================================================== JSON -> YAML
JSON_SOURCE = ('{"name":"demo","version":1.0e2,"tags":["a","true","x: y"],'
               '"deps":[{"id":1,"ok":true},[1,2],[]],'
               '"meta":{"empty":{},"note":null,"text":"line1\\nline2"}}')

JSON_EXPECTED = '''name: demo
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
  text: "line1\\nline2"
'''


class ExactOutputTests(unittest.TestCase):
    def test_python_to_javascript(self) -> None:
        self.assertEqual(transpile("py2js", PY_SOURCE), PY_EXPECTED)

    def test_typescript_to_javascript(self) -> None:
        self.assertEqual(transpile("ts2js", TS_SOURCE), TS_EXPECTED)

    def test_markdown_to_html(self) -> None:
        self.assertEqual(transpile("md2html", MD_SOURCE), MD_EXPECTED)

    def test_json_to_yaml(self) -> None:
        self.assertEqual(transpile("json2yaml", JSON_SOURCE), JSON_EXPECTED)

    def test_deterministic(self) -> None:
        for pair, src in (("py2js", PY_SOURCE), ("ts2js", TS_SOURCE),
                          ("md2html", MD_SOURCE), ("json2yaml", JSON_SOURCE)):
            self.assertEqual(transpile(pair, src), transpile(pair, src))


class PythonDetailTests(unittest.TestCase):
    def check(self, source: str, expected: str) -> None:
        self.assertEqual(transpile("py2js", source), expected)

    def test_unary_minus_binds_looser_than_power(self) -> None:
        self.check("print(-2 ** 2, (-2) ** 2)\n", "console.log(-(2 ** 2), (-2) ** 2);\n")

    def test_chained_comparison(self) -> None:
        self.check("x = 5\nprint(1 < x <= 9)\n", "let x = 5;\nconsole.log(1 < x && x <= 9);\n")

    def test_range_step_and_negative(self) -> None:
        self.check("for i in range(10, 0, -3):\n    print(i)\n",
                   "for (let i = 10; i > 0; i -= 3) {\n  console.log(i);\n}\n")

    def test_loop_bound_hoisted_when_not_invariant(self) -> None:
        self.check("xs = [1]\nfor k in range(len(xs)):\n    xs.append(k)\n",
                   "let xs = [1];\nconst __stop1 = xs.length;\n"
                   "for (let k = 0; k < __stop1; k++) {\n  xs.push(k);\n}\n")

    def test_variable_used_after_block_is_hoisted(self) -> None:
        self.check("if True:\n    y = 1\nelse:\n    y = 2\nprint(y)\n",
                   "let y;\nif (true) {\n  y = 1;\n} else {\n  y = 2;\n}\nconsole.log(y);\n")

    def test_loop_variable_read_after_loop_is_not_block_scoped(self) -> None:
        self.check("for i in range(3):\n    pass\nprint(i)\n",
                   "let i;\nfor (i = 0; i < 3; i++) {\n}\nconsole.log(i);\n")

    def test_reserved_word_identifiers_renamed(self) -> None:
        self.check("new = 1\nprint(new)\n", "let new_ = 1;\nconsole.log(new_);\n")

    def test_string_literals_reencoded(self) -> None:
        self.check("print('it\\'s \"q\"')\n", 'console.log("it\'s \\"q\\"");\n')

    def test_parenthesised_grouping_preserved(self) -> None:
        self.check("print(a - (b - c), (a + b) * c)\n", "console.log(a - (b - c), (a + b) * c);\n")


class TypeScriptDetailTests(unittest.TestCase):
    def check(self, source: str, expected: str) -> None:
        self.assertEqual(transpile("ts2js", source), expected)

    def test_nested_generics_close_correctly(self) -> None:
        self.check("let m: Map<string, Array<Array<number>>> = new Map<string, number[]>();\n",
                   "let m = new Map();\n")

    def test_shift_operator_is_not_a_generic_close(self) -> None:
        self.check("const r = a >> 2;\nconst q = a >= b;\n", "const r = a >> 2;\nconst q = a >= b;\n")

    def test_overloads_and_ambient_declarations_removed(self) -> None:
        self.check("declare const V: string;\nfunction f(a: string): void;\n"
                   "function f(a: any) { return a }\n",
                   "function f(a) {\n  return a;\n}\n")

    def test_this_parameter_and_optional_marker_erased(self) -> None:
        self.check("function g(this: Window, a?: number) { return a ?? 1 }\n",
                   "function g(a) {\n  return a ?? 1;\n}\n")

    def test_asi_without_semicolons(self) -> None:
        self.check("let a = 1\nlet b = a\nb++\n", "let a = 1;\nlet b = a;\nb++;\n")

    def test_arrow_returning_object_literal(self) -> None:
        self.check("const f = (x: number) => ({ x });\n", "const f = (x) => ({ x });\n")

    def test_type_only_import_dropped_entirely(self) -> None:
        self.check('import type { A } from "a";\nimport { type B } from "b";\nlet z = 1;\n', "let z = 1;\n")

    def test_enum_rejected_because_it_is_not_erasable(self) -> None:
        with self.assertRaises(TranspileError):
            transpile("ts2js", "enum Color { Red }\n")


class MarkdownDetailTests(unittest.TestCase):
    def check(self, source: str, expected: str) -> None:
        self.assertEqual(transpile("md2html", source), expected)

    def test_emphasis_nesting(self) -> None:
        self.check("***both*** and *a **b** c*\n",
                   "<p><em><strong>both</strong></em> and <em>a <strong>b</strong> c</em></p>\n")

    def test_html_is_escaped(self) -> None:
        self.check("a <script>alert(1)</script> & b\n",
                   "<p>a &lt;script&gt;alert(1)&lt;/script&gt; &amp; b</p>\n")

    def test_unsafe_link_scheme_is_neutralised(self) -> None:
        self.check("[x](javascript:alert(1))\n", '<p><a href="">x</a></p>\n')

    def test_loose_list_wraps_items_in_paragraphs(self) -> None:
        self.check("- a\n\n- b\n", "<ul>\n<li>\n<p>a</p>\n</li>\n<li>\n<p>b</p>\n</li>\n</ul>\n")

    def test_ordered_list_start_number(self) -> None:
        self.check("3. x\n4. y\n", '<ol start="3">\n<li>x</li>\n<li>y</li>\n</ol>\n')

    def test_hard_break_and_soft_break(self) -> None:
        self.check("a  \nb\nc\n", "<p>a<br />\nb\nc</p>\n")

    def test_underscore_inside_word_is_literal(self) -> None:
        self.check("snake_case_name\n", "<p>snake_case_name</p>\n")

    def test_unclosed_fence_runs_to_end(self) -> None:
        self.check("```\ncode\n", "<pre><code>code\n</code></pre>\n")

    def test_blockquote_with_list(self) -> None:
        self.check("> - a\n> - b\n", "<blockquote>\n<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n</blockquote>\n")

    def test_image(self) -> None:
        self.check("![a *b*](x.png)\n", '<p><img src="x.png" alt="a b" /></p>\n')


class JsonDetailTests(unittest.TestCase):
    def check(self, source: str, expected: str) -> None:
        self.assertEqual(transpile("json2yaml", source), expected)

    def test_top_level_scalar_and_empty_containers(self) -> None:
        self.check('"hi"', "hi\n")
        self.check("[]", "[]\n")
        self.check("{}", "{}\n")

    def test_strings_that_would_change_type_are_quoted(self) -> None:
        self.check('["1", "null", "2024-01-01", "", " x", "yes", "a#b", "a #b"]',
                   '- "1"\n- "null"\n- "2024-01-01"\n- ""\n- " x"\n- "yes"\n- a#b\n- "a #b"\n')

    def test_unicode_and_surrogate_pairs(self) -> None:
        self.check('"caf\\u00e9 \\ud83d\\ude00"', "café 😀\n")

    def test_numbers_are_normalised_for_yaml_float_rules(self) -> None:
        self.check("[1, -2, 1.5, 1e3, 2E-2, 12345678901234567890]",
                   "- 1\n- -2\n- 1.5\n- 1.0e+3\n- 2.0e-2\n- 12345678901234567890\n")


class ErrorTests(unittest.TestCase):
    def assertFails(self, pair: str, source: str, fragment: str) -> None:
        with self.assertRaises(TranspileError) as ctx:
            transpile(pair, source)
        self.assertIn(fragment, str(ctx.exception))

    def test_python_errors(self) -> None:
        self.assertFails("py2js", "if x:\nprint(1)\n", "Expected")
        self.assertFails("py2js", "x = (1,\n", "Unclosed bracket")
        self.assertFails("py2js", "  x = 1\n", "Unexpected indent")
        self.assertFails("py2js", "if x:\n        a = 1\n    b = 2\n", "Inconsistent dedent")
        self.assertFails("py2js", "return 1\n", "outside function")
        self.assertFails("py2js", "break\n", "outside loop")
        self.assertFails("py2js", "s = 'abc\n", "Unterminated string")
        self.assertFails("py2js", "for i in range(0, 5, n):\n    pass\n", "integer literal")

    def test_typescript_errors(self) -> None:
        self.assertFails("ts2js", "let x: = 1;\n", "type")
        self.assertFails("ts2js", "class A {}\n", "classes")
        self.assertFails("ts2js", "let s = 'abc\n", "Unterminated")

    def test_json_errors(self) -> None:
        self.assertFails("json2yaml", '{"a": 1,}', "Expected STRING")
        self.assertFails("json2yaml", '{"a": 1, "a": 2}', "Duplicate key")
        self.assertFails("json2yaml", "[1 2]", "Expected")
        self.assertFails("json2yaml", "{'a': 1}", "Unexpected character")
        self.assertFails("json2yaml", '[1] 2', "trailing")

    def test_error_reports_position(self) -> None:
        with self.assertRaises(TranspileError) as ctx:
            transpile("json2yaml", '{\n  "a": ,\n}')
        self.assertEqual((ctx.exception.line, ctx.exception.col), (2, 8))


# ------------------------------------------------------------------ semantic checks
NODE = shutil.which("node")

SEMANTIC_PROGRAMS = [
    "total = 0\nfor i in range(1, 11):\n    if i % 2 == 0:\n        total += i * i\nprint(total)\n",
    "def fib(n):\n    a = 0\n    b = 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\nprint(fib(10))\n"
    .replace("        a, b = b, a + b\n", "        t = a + b\n        a = b\n        b = t\n"),
    "print(-7 % 3, 7 % -3, -7 // 2, 7 // -2, 2 ** 3 ** 2, -2 ** 2, 10 / 4)\n",
    "n = 27\nsteps = 0\nwhile n != 1:\n    if n % 2 == 0:\n        n = n // 2\n    else:\n        n = 3 * n + 1\n    steps += 1\nprint(steps)\n",
    "def gcd(a, b):\n    while b != 0:\n        t = b\n        b = a % b\n        a = t\n    return a\nprint(gcd(48, 18), gcd(17, 5))\n",
    "xs = [3, 1, 2]\nfor k in range(len(xs)):\n    xs.append(xs[k] * 2)\nprint(len(xs), xs[-1], xs[0])\n",
    "for i in range(5, 0, -2):\n    print(i)\nprint(1 < 2 < 3, 3 > 2 > 2, not 0)\n",
    "def f(x):\n    if x > 0:\n        r = 1\n    else:\n        r = -1\n    return r\nprint(f(3), f(-3))\n",
]


@unittest.skipUnless(NODE and shutil.which("python3"), "node and python3 required")
class DifferentialExecutionTests(unittest.TestCase):
    """Run the Python source and the generated JavaScript; stdout must be identical."""

    @staticmethod
    def run_cmd(cmd: list[str], source: str) -> str:
        done = subprocess.run(cmd, input=source, capture_output=True, text=True, timeout=30)
        if done.returncode != 0:
            raise AssertionError(done.stderr)
        return done.stdout

    @staticmethod
    def normalise(text: str) -> str:
        return text.replace("True", "true").replace("False", "false")

    def test_python_and_generated_js_agree(self) -> None:
        for source in SEMANTIC_PROGRAMS:
            with self.subTest(source=source):
                expected = self.normalise(self.run_cmd(["python3", "-"], source))
                js = transpile("py2js", source)
                actual = self.run_cmd([NODE, "-"], js)
                self.assertEqual(actual, expected)


try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


def _random_json(rng: random.Random, depth: int = 0):
    kinds = ["str", "int", "float", "bool", "null"]
    if depth < 4:
        kinds += ["list", "dict", "list", "dict"]
    kind = rng.choice(kinds)
    if kind == "str":
        pool = ["", " ", "a", "yes", "No", "null", "~", "1", "1.5", "0x1f", "1e3", "-", "- x", "a: b",
                "a:b", "#c", "a #c", "x\ny", "tab\t", "q\"uote", "'s'", "{x}", "[y]", "é", "😀", "---",
                "2024-05-06", "12:30", "on", "<<", "=", "@at", "`bt", "!tag", "&anc", "*star", "%pct",
                "trailing ", " leading", "back\\slash", "0o17", ".inf", ".5", "+1", "1_000", "true", "?"]
        return rng.choice(pool) if rng.random() < 0.8 else "".join(rng.choice("ab :#-{}\n\"'") for _ in range(rng.randint(0, 6)))
    if kind == "int":
        return rng.choice([0, 1, -1, 42, 10 ** 15, -(10 ** 12)])
    if kind == "float":
        return rng.choice([0.5, -1.25, 1e22, 1e-7, 3.14159, 2.5e10])
    if kind == "bool":
        return rng.random() < 0.5
    if kind == "null":
        return None
    if kind == "list":
        return [_random_json(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {rng.choice(["k", "key", "n", "true", "1", "a b", "x:y", "", "é", "null", "yes"]) + str(i):
            _random_json(rng, depth + 1) for i in range(rng.randint(0, 4))}


@unittest.skipUnless(yaml is not None, "PyYAML required for the round-trip check")
class YamlRoundTripTests(unittest.TestCase):
    """Convert random JSON documents and let an independent YAML parser read them back."""

    def test_round_trip_matches_json(self) -> None:
        import json
        rng = random.Random(20260101)  # fixed seed: the test itself is deterministic
        for n in range(1500):
            value = _random_json(rng)
            text = json.dumps(value, ensure_ascii=rng.random() < 0.5)
            out = transpile("json2yaml", text)
            self.assertEqual(yaml.safe_load(out), json.loads(text), msg=f"case {n}: {text!r}\n{out}")


@unittest.skipUnless(NODE, "node required")
class GeneratedJavaScriptIsValidTests(unittest.TestCase):
    """`node --check` parses (without running) the generated JavaScript."""

    def test_outputs_are_syntactically_valid(self) -> None:
        import os
        import tempfile
        for pair, source in (("py2js", PY_SOURCE), ("ts2js", TS_SOURCE)):
            js = transpile(pair, source)
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "out.mjs")  # .mjs: ES module syntax (imports) allowed
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(js)
                done = subprocess.run([NODE, "--check", path], capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, msg=done.stderr)


try:
    from markdown_it import MarkdownIt  # type: ignore
except ImportError:  # pragma: no cover
    MarkdownIt = None

MD_CORPUS = [
    "# H1\n\nPara *em* **strong** `code`\n",
    "- a\n- b\n  - c\n- d\n",
    "1. a\n2. b\n\n3. c\n",
    "> q\n> r\n\nafter\n",
    "***x*** _y_ __z__ a*b*c snake_case_x\n",
    "[a](http://x.com 'T') ![i](p.png \"t\")\n",
    "```py\nx=1\n\ny=2\n```\n",
    "---\n\n* * *\n",
    "line1  \nline2\\\nline3\n",
    "- a\n\n- b\n\n  para\n- c\n",
    "- item\n\n  ```\n  code\n  ```\n- next\n",
    "> - a\n>   b\n> - c\n",
    "a & b < c > d \"q\"\n",
    "*a **b** c*\n\n**a *b* c**\n",
    MD_SOURCE,
]


@unittest.skipUnless(MarkdownIt is not None, "markdown-it-py required for the reference comparison")
class MarkdownReferenceTests(unittest.TestCase):
    """Compare against an independent CommonMark implementation on the supported subset."""

    def test_matches_reference_renderer(self) -> None:
        reference = MarkdownIt("commonmark")
        for source in MD_CORPUS:
            with self.subTest(source=source):
                self.assertEqual(transpile("md2html", source), reference.render(source))


if __name__ == "__main__":
    unittest.main()
