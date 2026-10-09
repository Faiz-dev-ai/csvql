# Streaming and comparison semantics

`execute(query, csv_path)` returns a generator. Opening and header validation
happen on first iteration. Exhaust it or call `close()` when stopping early;
the CLI uses `contextlib.closing`. Earlier rows may print before a later input
error. Expected errors go to stderr and cause exit status 1.

The engine retains the expression tree, headers, and current row for ordinary scans, not all
matching results. Memory for ordinary scans depends on record size and CSV buffering. LIMIT counts
matches after filtering and stops scanning early for ordinary scans. Grouping
and sorting retain additional state and apply LIMIT after those operations; see
[analytical semantics](analytics.md). LIMIT 0 checks the header and
all referenced columns but does not read data rows. Unscanned data is not
validated. UTF-8 input with or without a BOM is supported.

## Literal-directed comparisons

- Unquoted SQL numbers become exact `Decimal` values. No float conversion,
  arithmetic, or rounding occurs during comparison.
- CSV numeric cells accept the same forms as SQL: integers, negative numbers,
  and decimals such as `1.5`, `.5`, and `-.5`. Surrounding whitespace is ignored
  for numeric comparisons. Scientific notation and leading plus are unsupported.
- Single-quoted SQL values are case-sensitive, lexicographically compared text.
  Whitespace and leading zeros are preserved: `001` equals numeric `1`, but
  does not equal text `'1'`.
- A short CSV row's absent cell (`None`) yields unknown for every comparison.
- An empty or nonnumeric cell in a numeric comparison yields unknown, including
  for `!=`. NaN and Infinity are not supported numeric values.
- An explicitly empty cell is an empty string and matches the text literal `''`.
- WHERE keeps only true results. Without WHERE all rows are returned.
- Non-aggregate output values remain original strings (or `None`). Aggregate
  output types are documented in [analytical semantics](analytics.md).

## Boolean logic

Comparisons bind before NOT, then AND, then OR. Parentheses override grouping.
Evaluation short-circuits, but all referenced columns are validated up front.

| A | B | A AND B | A OR B |
|---|---|---|---|
| true | true | true | true |
| true | false | false | true |
| true | unknown | unknown | true |
| false | true | false | true |
| false | false | false | false |
| false | unknown | false | unknown |
| unknown | true | unknown | true |
| unknown | false | false | unknown |
| unknown | unknown | unknown | unknown |

NOT flips true/false and preserves unknown. Therefore NOT does not accidentally
include missing/nonnumeric cells. This extends the earlier filtering behavior:
unknown values were previously simply excluded by single comparisons.

Duplicate headers and extra fields are rejected to avoid silent data loss.
Malformed CSV quoting raises a readable error. These are CSVQL's explicit
rules, not a full SQL NULL/type system. IS NULL is not implemented. FROM remains
a descriptive name; the supplied file path determines which CSV is read.
