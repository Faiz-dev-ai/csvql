# CSVQL

CSVQL is a small SQL-like query engine that reads CSV files directly. It uses a
handwritten lexer, a recursive-descent parser, and a streaming executor. It has
no runtime dependencies outside the Python standard library.

## Quick start

Requires Python 3.10 or newer. From the repository folder:

```bash
python3 cli.py "SELECT name, salary FROM employees WHERE salary >= 400000" employees.csv
```

Output:

```text
{'name': 'Arjun', 'salary': '450000'}
{'name': 'Meena', 'salary': '610000'}
{'name': 'Suresh', 'salary': '650000'}
```

## Install locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
csvql --help
csvql --version
```

Installation uses setuptools as a build dependency; pip may need network access
to obtain it. No runtime dependencies are downloaded for CSVQL itself. The
local package version is 0.1.0; this does not imply a published PyPI release.

The **query comes first, file path second** for every entry point:

```bash
csvql "SELECT name FROM employees LIMIT 2" employees.csv
python -m csvql "SELECT name FROM employees LIMIT 2" employees.csv
python cli.py "SELECT name FROM employees LIMIT 2" employees.csv
```

## Combined conditions

```bash
csvql "SELECT name FROM employees WHERE salary >= 300000 AND (city = 'Bengaluru' OR city = 'Pune') AND NOT name = 'Arjun' LIMIT 2;" employees.csv
```

Returns Karthik and Anjali. `LIMIT` counts matching output rows, not input rows.
`LIMIT 0` validates the file/header and columns but reads no data rows.

Double quotes denote identifiers; single quotes denote text. For a CSV with
headers `First Name` and `Salary`, for example:

```bash
csvql 'SELECT "First Name", "Salary" FROM company_data WHERE "Salary" >= 17000' company_data.csv
```

`company_data.csv` is an optional local dataset and is not included in Git.
Use doubled quotes to escape quotes: `'O''Brien'` and `"a""b"`.

## Supported SQL subset

```text
SELECT (* | item [, item ...]) FROM table
[WHERE expression]
[GROUP BY column [, column ...]]
[ORDER BY item [ASC | DESC] [, item [ASC | DESC] ...]]
[LIMIT non_negative_integer]
[;]

item := column | COUNT(*) | COUNT(column) | SUM(column) | AVG(column) | MIN(column) | MAX(column)
expression := comparisons combined with NOT, AND, OR, and parentheses
comparison := column (= | != | < | <= | > | >=) (number | 'text')
```

- Keywords are case-insensitive; column names and text values are case-sensitive.
- Precedence, strongest first: parentheses/comparisons, `NOT`, `AND`, `OR`.
  `a = 1 OR b = 1 AND c = 1` means `a = 1 OR (b = 1 AND c = 1)`.
- Numeric literals support integers and decimals, including `-1.5` and `.5`.
- One optional trailing semicolon is accepted; multiple statements are rejected.
- `FROM` is a descriptive name; the separate file path selects the actual CSV.
  It is not a table registry and need not match the filename.
- Reserved words (including `AND`, `OR`, `NOT`, `LIMIT`, `GROUP`, `ORDER`,
  `BY`, `ASC`, `DESC`, and aggregate function names) must be double-quoted when
  used as column names.

## Aggregates, grouping, and sorting

```bash
csvql "SELECT COUNT(*), SUM(salary), AVG(salary) FROM employees" employees.csv
csvql "SELECT department, COUNT(*), AVG(salary) FROM employees GROUP BY department ORDER BY AVG(salary) DESC" employees.csv
csvql "SELECT name, salary FROM employees ORDER BY salary DESC LIMIT 3" employees.csv
```

COUNT, SUM, AVG, MIN, and MAX work globally or per group. WHERE filters before
aggregation; LIMIT applies after grouping/sorting. ORDER BY supports multiple
keys and ASC/DESC. Every selected plain column must be grouped in aggregate
queries. See [analytical semantics and memory limits](docs/analytics.md).

SUM uses exact decimal addition. AVG rounds to 28 significant decimal digits.
The CLI prints their values as decimal strings. COUNT returns an integer;
MIN/MAX retain the chosen source string. Empty aggregates return None except
COUNT, which returns 0.

ORDER BY compares numeric-looking cells numerically, then text lexicographically;
missing cells always sort last. Groups use the original text as their keys.

## Values and missing data

Unquoted numeric literals use exact `Decimal` comparisons. Quoted literals use
text comparisons, preserving whitespace and leading zeros: `code = 1` matches
both `001` and `1`, while `code = '1'` matches only `1`.

Missing cells produce **unknown**, as do empty/nonnumeric cells used in numeric
comparisons. `WHERE` keeps only true results. `NOT unknown` stays unknown;
`false AND unknown` is false and `true OR unknown` is true. An explicitly empty
cell can match `''`. See [the complete rules](docs/comparisons.md).

Files are read as UTF-8 (an optional BOM is accepted). Output is one Python
row dictionary per line, preserving source strings and representing missing
cells as `None`. Aggregated values follow the rules above. This is not CSV or JSON output.

## Architecture and streaming

```text
SQL → lexer → tokens → parser → expression tree
                                      ↓
CSV → validate headers → filter rows → optional aggregate/group → optional sort
                                                               ↓
                                                   project → LIMIT → output
```

Filtering/projection queries yield results one at a time without retaining
earlier rows. Global aggregates retain only accumulator state. GROUP BY stores
per-group summaries, and ORDER BY buffers rows before sorting. Default limits
are 100,000 groups and 100,000 sorted rows; use `--max-groups` and
`--max-sort-rows` to configure them. These count limits are not byte-level RAM
limits. There is no disk spilling or external sort.

CSV field-size limits still apply. For ordinary scans, LIMIT stops reading once
enough matches are produced. Sorting/grouping must process the relevant input
before LIMIT applies. Unscanned rows are not validated.

An input error late in the file can occur after earlier results have printed.
Expected errors go to stderr with exit status 1; command-argument errors use
status 2. Success uses status 0.

Python API:

```python
from contextlib import closing
from csvql.lexer import tokenize
from csvql.parser import parse
from csvql.executor import execute

query = parse(tokenize("SELECT name FROM employees LIMIT 2"))
with closing(execute(query, "employees.csv")) as rows:
    for row in rows:
        print(row)
```

Opening and validation happen on first iteration. Close an iterator if stopping
early. Calling `list(rows)` deliberately collects all results in memory.

## Tests

```bash
python3 -B -m unittest discover -s tests -v
```

Tests cover syntax, exact comparisons, errors, lazy reads, file cleanup,
short-circuiting, all branches' column validation, and early limits. Boolean
precedence and three-valued results are cross-checked against SQLite across
all combinations of true, false, and missing numeric values. Analytical tests
cover grouping against SQLite, stable sorting, aggregate precision, empty
inputs, malformed queries, and resource-limit errors.

## Benchmarks

```bash
python3 -B benchmarks/benchmark.py --rows 10000 100000 500000 --output benchmarks/results.json
```

The script generates temporary data, then runs each measurement in a fresh
process. It compares streaming consumption against collecting the **same
engine's output** in a list. Data generation and terminal output are excluded.
It records file size, row count, elapsed time, throughput, and process peak RSS
where supported. `--trace` additionally measures Python allocations and adds
timing overhead. See [measured results and limitations](benchmarks/README.md).

## Current limits and roadmap

- No joins, arithmetic expressions, aliases, subqueries, `HAVING`, `DISTINCT`,
  `IS NULL`, `LIKE`, `IN`, `OFFSET`, or writes.
- No external sorting, disk spilling, or top-k optimization for ORDER BY LIMIT.
- No scientific notation, leading `+`, or trailing-dot numeric literals.
- Comparisons accept a column on the left and a literal on the right.
- Expression trees deeper than 128 nodes are rejected; extremely nested parser
  input also fails with a readable error.
- Single-file scans only; no optimizer, indexes, or full SQL type system.
- Multi-GB performance has not yet been established by the checked-in benchmark.

The planned eight implementation stages are present. Future extensions could
include external sorting, disk spilling, output formats, and multi-GB benchmarks.
The project implements a documented SQL subset, not the full SQL standard.
