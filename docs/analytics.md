# Aggregates, grouping, and ordering

CSVQL supports this clause order:

```sql
SELECT department, COUNT(*), SUM(salary), AVG(salary), MIN(salary), MAX(salary)
FROM employees
WHERE salary >= 300000
GROUP BY department
ORDER BY SUM(salary) DESC, department ASC
LIMIT 3;
```

Each clause is optional after FROM, but if present must follow the shown order.
Filtering happens before grouping; sorting and LIMIT apply to final results.

## Aggregates

| Function | Rule |
|---|---|
| COUNT(*) | Count all filtered rows. |
| COUNT(column) | Count cells that are present. An empty string counts; an absent cell does not. |
| SUM(column) | Exact decimal sum of numeric cells. Skip empty/whitespace-only and absent cells; reject other nonnumeric text. |
| AVG(column) | Sum divided by the count of numeric cells, rounded to 28 significant decimal digits using round-half-even. |
| MIN(column), MAX(column) | Skip absent cells. Use numeric comparison for numeric-looking cells, case-sensitive text comparison otherwise; numbers precede text. Preserve the chosen original CSV string. |

The existing numeric syntax applies: integers, negative numbers, and decimal
fractions, without scientific notation or leading plus signs. Numeric values
are stripped of surrounding whitespace. NaN and Infinity are text, not numbers.
SUM/AVG reject them, while MIN/MAX can compare them as text.

SUM is accumulated without Decimal's usual 28-digit addition rounding. AVG is
explicitly rounded because a fraction such as 1/3 cannot be represented as a
finite decimal. Empty strings are text values for MIN/MAX, even though they are
skipped by SUM/AVG. These rules are explicit CSVQL choices, not schema inference.

The Python API returns int for COUNT, Decimal for SUM/AVG, and original strings
for MIN/MAX. The CLI renders Decimal results as ordinary decimal strings:

```text
{'COUNT(*)': 8, 'SUM(salary)': '3345000', 'AVG(salary)': '418125'}
```

With zero matching rows, an ungrouped aggregate still returns one result:
COUNT is 0 and SUM/AVG/MIN/MAX are None. Grouped queries return no rows when no
input rows match. LIMIT 0 suppresses even the global aggregate result.

## Grouping

GROUP BY accepts one or more column names, including double-quoted names.
Group keys preserve original text: `001` and `1` are different groups. Empty
strings and absent cells are also different groups. Missing values group
together. Without ORDER BY, groups appear in first-encountered input order.

Every plain column in SELECT or ORDER BY must appear in GROUP BY when any
aggregate or grouping is used. SELECT * with aggregates/grouping is rejected.
GROUP BY without aggregate functions is supported. Aggregate expressions may
appear in ORDER BY even if not selected. No HAVING, DISTINCT, aliases, ordinal
sorting, nested aggregate functions, or expressions inside aggregate arguments
are implemented.

Output dictionary names must be unique; duplicate names are rejected rather
than silently overwritten. COUNT(*) and COUNT("*") are distinct: the latter
counts a column literally named `*`.

## Sorting

ORDER BY accepts multiple columns or aggregate expressions, each with optional
ASC (default) or DESC. Ordinary queries may sort on a column they do not select.
Ties retain input order (or group encounter order).

Values sort by these rules:

1. Numeric-looking values compare as exact Decimal numbers.
2. Nonnumeric values compare as case-sensitive text.
3. Absent values (None) always sort last, both ascending and descending.

Ascending puts numbers before text; descending reverses those two categories.
Empty strings are text, not missing values. Thus `2` sorts before `10`, while
numeric-looking identifiers such as `001` and `1` tie. There is no CAST or
explicit text-sort override yet.

MIN/MAX use the same number/text ordering, skipping missing values. They retain
the first encountered original value on equal keys.

## Resource limits

| Operation | State retained |
|---|---|
| Filter/project without sorting/grouping | Current row and query/header state |
| Global aggregate | One accumulator per aggregate (integer/decimal state can grow in digit count) |
| GROUP BY | One group key and accumulator set per group |
| ORDER BY | All filtered rows, or all resulting group rows, plus sort keys |

Default limits are **100,000 groups** and **100,000 rows to sort**. Exceeding a
limit raises CsvqlError; the CLI reports it and exits with status 1. These are
count limits, not a byte-level RAM guarantee. Wide rows and many aggregates can
still use substantial memory. There is no disk spilling or external sort.

Override explicitly when appropriate for your data and available memory:

```bash
csvql --max-groups 200000 --max-sort-rows 200000 \
  "SELECT department, COUNT(*) FROM employees GROUP BY department ORDER BY COUNT(*) DESC" employees.csv
```

Python callers can pass `max_groups=` and `max_sort_rows=` to execute(). Both
must be positive integers.

Sorting must inspect all relevant rows even with LIMIT 1; it is not a top-k
optimization. Grouping also scans all matching rows before yielding results.
LIMIT 0 validates syntax, headers, and referenced columns but reads no data.
Ordinary filtering queries still stop scanning once LIMIT matches are yielded.
