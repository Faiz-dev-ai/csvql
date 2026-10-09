# CSVQL

**Run SQL-like queries directly on a CSV file—no database or import step.**

Querying a CSV often means importing it into a database or writing a one-off
script. CSVQL parses the query itself with a handwritten lexer and a
recursive-descent parser. Ordinary filtering and projection queries process
rows one at a time without accumulating the results. It is pure Python, with
no runtime dependencies beyond the standard library.

```bash
python3 cli.py "SELECT department, COUNT(*), AVG(salary) FROM employees GROUP BY department ORDER BY AVG(salary) DESC" employees.csv
```

```text
{'department': 'Marketing', 'COUNT(*)': 2, 'AVG(salary)': '630000'}
{'department': 'Engineering', 'COUNT(*)': 4, 'AVG(salary)': '356250'}
{'department': 'Sales', 'COUNT(*)': 2, 'AVG(salary)': '330000'}
```

**Measured:** peak process memory for a streaming filter query stayed around
23 MB from 10,000 to 500,000 rows. Collecting the same output in a list reached
about 222 MB at 500,000 rows. Grouping and sorting retain additional state;
these measurements do not apply to them. See [Benchmarks](#benchmarks).

## Contents

- [Quick start](#quick-start)
- [Install locally](#install-locally)
- [Query language](#query-language)
- [Aggregates, grouping, and sorting](#aggregates-grouping-and-sorting)
- [Values and missing data](#values-and-missing-data)
- [How it works](#how-it-works)
- [Python API](#python-api)
- [Tests](#tests)
- [Benchmarks](#benchmarks)
- [Limits and roadmap](#limits-and-roadmap)

## Quick start

Requires **Python 3.10 or newer**. Clone the repository and run the included
sample without installing the package:

```bash
git clone https://github.com/Faiz-dev-ai/csvql.git
cd csvql
python3 cli.py "SELECT name, salary FROM employees WHERE salary >= 400000" employees.csv
```

```text
{'name': 'Arjun', 'salary': '450000'}
{'name': 'Meena', 'salary': '610000'}
{'name': 'Suresh', 'salary': '650000'}
```

Already have the repository? Run the query from its folder.
The **query comes first, file path second** for every entry point.

## Install locally

From the repository folder, on macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
csvql --help
csvql --version
```

Installation uses setuptools as a build dependency, so pip may need network
access to fetch it. CSVQL has no runtime package dependencies. The local
package version is 0.1.0; this does not imply a published PyPI release.

All three entry points accept the same arguments:

```bash
csvql "SELECT name FROM employees LIMIT 2" employees.csv
python -m csvql "SELECT name FROM employees LIMIT 2" employees.csv
python cli.py "SELECT name FROM employees LIMIT 2" employees.csv
```

## Query language

```text
SELECT (* | item [, item ...]) FROM table
[WHERE expression]
[GROUP BY column [, column ...]]
[ORDER BY item [ASC | DESC] [, item [ASC | DESC] ...]]
[LIMIT non_negative_integer]
[;]

item       := column | COUNT(*) | COUNT(column) | SUM(column) | AVG(column) | MIN(column) | MAX(column)
expression := comparisons combined with NOT, AND, OR, and parentheses
comparison := column (= | != | < | <= | > | >=) (number | 'text')
```

### Combined conditions

```bash
csvql "SELECT name FROM employees WHERE salary >= 300000 AND (city = 'Bengaluru' OR city = 'Pune') AND NOT name = 'Arjun' LIMIT 2;" employees.csv
```

Returns Karthik and Anjali. `LIMIT` counts output rows, not input rows.
`LIMIT 0` validates the header and referenced columns but reads no data rows.

- Keywords are case-insensitive; column names and text values are case-sensitive.
- Precedence, strongest first: parentheses/comparisons, `NOT`, `AND`, `OR`.
  `a = 1 OR b = 1 AND c = 1` means `a = 1 OR (b = 1 AND c = 1)`.
- Numeric literals support integers and decimals, including `-1.5` and `.5`.
- One optional trailing semicolon is accepted; multiple statements are rejected.
- `FROM` is a descriptive name. The file path argument selects the actual CSV;
  the name need not match the filename.
- Reserved words—including `SELECT`, `FROM`, `WHERE`, `AND`, `OR`, `NOT`,
  `LIMIT`, `GROUP`, `ORDER`, `BY`, `ASC`, `DESC`, and aggregate function names—must
  be double-quoted when used as column names.

### Quoted column names

Double quotes denote identifiers; single quotes denote text. Use doubled
quotes to escape a quote: `'O''Brien'` and `"a""b"`.

For a self-contained example, save this as a new file named `people.csv`:

```csv
First Name,Salary
Asha,18000
Ravi,16000
Meera,21000
```

Then run:

```bash
csvql 'SELECT "First Name", "Salary" FROM people WHERE "Salary" >= 17000' people.csv
```

```text
{'First Name': 'Asha', 'Salary': '18000'}
{'First Name': 'Meera', 'Salary': '21000'}
```

## Aggregates, grouping, and sorting

```bash
csvql "SELECT COUNT(*), SUM(salary), AVG(salary) FROM employees" employees.csv
csvql "SELECT department, COUNT(*), AVG(salary) FROM employees GROUP BY department ORDER BY AVG(salary) DESC" employees.csv
csvql "SELECT name, salary FROM employees ORDER BY salary DESC LIMIT 3" employees.csv
```

- Aggregates work globally or per group. `WHERE` filters before aggregation;
  `LIMIT` applies after grouping and sorting.
- `COUNT(*)` counts rows. `COUNT(column)` counts present cells, including empty
  strings, but excludes absent cells.
- `SUM` and `AVG` skip empty/whitespace-only and absent cells, and reject other
  nonnumeric text. `SUM` uses exact decimal addition; `AVG` rounds to 28
  significant decimal digits using round-half-even.
- The CLI prints `SUM`/`AVG` results as decimal strings. `COUNT` returns an
  integer; `MIN`/`MAX` preserve the chosen source string.
- With zero matching rows, an **ungrouped** aggregate returns one result:
  `COUNT` is 0 and the other aggregates are `None`. A grouped query returns
  **no rows**. A file with no header is an error. `LIMIT 0` suppresses output.
- Plain columns selected or ordered in an aggregate query must appear in
  `GROUP BY`. Group keys preserve original text, so `001` and `1` are distinct.
- `ORDER BY` supports multiple keys, `ASC` (default), and `DESC`. Ties retain
  input order. Numeric-looking cells compare numerically; other cells compare
  as case-sensitive text. Ascending puts numbers before text; descending
  reverses these categories. Absent cells always sort last.
- `MIN`/`MAX` use the same number/text ordering, skipping absent cells.

See [analytical semantics and memory limits](docs/analytics.md) for the full
rules, including empty cells, aggregate output types, and resource limits.

## Values and missing data

Unquoted numeric literals use exact `Decimal` comparisons. Quoted literals use
text comparisons, preserving whitespace and leading zeros: `code = 1` matches
both `001` and `1`, while `code = '1'` matches only `1`.

Missing cells produce **unknown**, as do empty or nonnumeric cells used in a
numeric comparison. `WHERE` retains only true results. `NOT unknown` stays
unknown, `false AND unknown` is false, and `true OR unknown` is true. An
explicitly empty cell can match `''`. See [the complete rules](docs/comparisons.md).

Files are read as UTF-8, with an optional BOM. Output is one Python row
dictionary per line, preserving source strings and showing absent cells as
`None`. Aggregate values follow the rules above. This is human-readable output,
not a CSV or JSON serialization format.

## How it works

```text
SQL -> lexer -> tokens -> parser -> structured query + expression tree
                                                |
                                                v
CSV -> validate headers -> filter -> optional aggregate/group -> optional sort
                                                                     |
                                                                     v
                                                         project -> LIMIT -> output
```

1. **Lexer:** recognizes tokens and rejects unexpected characters and unclosed
   quotes with their positions.
2. **Parser:** checks grammar and builds the query structure. `parse_or()` calls
   `parse_and()`, which calls `parse_not()`. `parse_not()` handles negation and
   parentheses, then delegates comparisons to `parse_condition()`. Precedence
   follows from this structure.
3. **Executor:** validates every referenced column against the CSV header before
   processing data rows, then filters rows lazily. The analytics module handles
   grouping, aggregation, and sorting when requested.

| Operation | State retained |
|---|---|
| Filtering/projection | Query, headers, and the current row; no accumulated results |
| Global aggregates | Accumulator state per aggregate |
| `GROUP BY` | Group keys and aggregate state per group |
| `ORDER BY` | Rows and sort keys |

For comparable row sizes, ordinary scans do not retain more results as row
count grows. Memory still depends on row size, query size, and reader buffering;
CSV field-size limits apply. Aggregate accumulator digit counts can also grow.

Grouping and sorting default to limits of **100,000 groups** and **100,000 rows
being sorted**. Configure them with `--max-groups` and `--max-sort-rows`.
These are count limits, not byte-level RAM limits. There is no disk spilling
or external sort.

For ordinary scans, `LIMIT` stops reading after enough matches. Grouping and
sorting must process the relevant input before `LIMIT` applies. Unscanned rows
are not validated.

Expected errors go to stderr as `Error: ...` and use exit status 1. Command-line
argument errors use status 2; success uses status 0. Because results stream, a
late input error may appear after earlier results have printed.

```bash
csvql "SELECT nme FROM employees" employees.csv
```

```text
Error: Unknown column 'nme'. Available columns: id, name, department, salary, city
```

## Python API

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

Opening and validation happen on first iteration. Close the iterator when
stopping early. Calling `list(rows)` deliberately collects all results in memory.

## Tests

```bash
python3 -B -m unittest discover -s tests -v
```

The suite contains **82 test methods**, including parameterized subcases. It
covers syntax, exact comparisons, error paths, lazy reads, file cleanup,
short-circuiting, validation of every condition branch, and early limits.
Boolean precedence and three-valued results are cross-checked against SQLite,
as are selected grouped-query results. Analytics tests cover stable sorting,
aggregate precision, empty inputs, malformed queries, and resource-limit errors.

## Benchmarks

```bash
python3 -B benchmarks/benchmark.py --rows 10000 100000 500000 --output benchmarks/results.json
```

The script generates temporary data and runs each measurement in a fresh
process. It compares streaming consumption against collecting **the same
engine's output** in a list—not against a historical version. Data generation
and terminal output are excluded. It records file size, row count, elapsed
time, throughput, and peak process memory (RSS) where supported. `--trace`
also measures Python allocations and adds timing overhead.

Recorded run: Python 3.11.15, macOS arm64. Query:

```sql
SELECT id, department, salary FROM generated WHERE salary >= 0
```

| Rows | CSV size (MB) | Streaming peak RSS (MB) | Collected-list peak RSS (MB) |
|---:|---:|---:|---:|
| 10,000 | 0.239 | 22.68 | 26.66 |
| 100,000 | 2.489 | 22.74 | 62.06 |
| 500,000 | 12.889 | 22.76 | 221.81 |

MB means 1,000,000 bytes. Values come from the saved
[raw measurements](benchmarks/results.json).

The measurements show the memory cost of retaining results as row count grows.
They do **not** establish cold-disk throughput, performance on files larger than
RAM, or the cost of grouping and sorting. Each case ran once, and freshly
generated files may have been served from the OS cache. See the
[method and limitations](benchmarks/README.md).

## Limits and roadmap

Not supported:

- Joins, arithmetic expressions, aliases, subqueries, `HAVING`, `DISTINCT`,
  `IS NULL`, `LIKE`, `IN`, `OFFSET`, and writes.
- External sorting, disk spilling, or a top-k optimization for `ORDER BY ... LIMIT`.
- Scientific notation, a leading `+`, and trailing-dot numeric literals such as `5.`.
- Column-to-column comparisons: the left side must be a column, the right a literal.

Expression depth greater than **128** is rejected; extremely nested parser input
also fails with a readable error. CSVQL scans a single supplied file and has no
optimizer, indexes, or full SQL type system. Multi-GB performance has not been
established by the checked-in benchmark.

Possible extensions include external merge sorting, spilling groups to disk,
CSV/JSON output, performance comparisons with SQLite and pandas, and multi-GB
benchmarks. CSVQL implements a documented SQL subset, not the full standard.
