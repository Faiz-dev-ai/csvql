"""Stream projected CSV rows with literal-directed comparisons."""

import csv
from decimal import Decimal

from csvql.analytics import (DEFAULT_MAX_GROUPS, DEFAULT_MAX_SORT_ROWS,
                             aggregate_rows, label, sorted_rows, validate_query)
from csvql.ast import Boolean, Negation, referenced_columns
from csvql.errors import CsvqlError
from csvql.lexer import NUMBER


def matches(row, condition):
    """WHERE includes only true results, not false or unknown results."""
    return evaluate(row, condition) is True


def evaluate(row, condition):
    """Three-valued evaluation: None represents an unknown comparison."""
    if condition is None:
        return True
    if isinstance(condition, Negation):
        value = evaluate(row, condition.operand)
        return None if value is None else not value
    if isinstance(condition, Boolean):
        left = evaluate(row, condition.left)
        if condition.operator == "AND":
            if left is False:
                return False
            right = evaluate(row, condition.right)
            if right is False:
                return False
            return None if left is None or right is None else True
        if left is True:
            return True
        right = evaluate(row, condition.right)
        if right is True:
            return True
        return None if left is None or right is None else False

    column, operator, value = condition
    row_value = row[column]
    if row_value is None:
        return None
    if isinstance(value, Decimal):
        numeric_text = row_value.strip()
        if NUMBER.fullmatch(numeric_text) is None:
            return None
        row_value = Decimal(numeric_text)

    if operator == ">":
        return row_value > value
    if operator == "<":
        return row_value < value
    if operator == ">=":
        return row_value >= value
    if operator == "<=":
        return row_value <= value
    if operator == "!=":
        return row_value != value
    if operator == "=":
        return row_value == value
    raise CsvqlError(f"Unknown operator: {operator}")


def execute(query, csv_path, *, max_groups=DEFAULT_MAX_GROUPS, max_sort_rows=DEFAULT_MAX_SORT_ROWS):
    """Yield query results. Grouping/sorting buffer bounded state, scans stream.

    LIMIT applies after grouping and sorting. Exhaust or close this generator
    to release the file. Validation starts on the first iteration.
    """
    for name, value in (("max_groups", max_groups), ("max_sort_rows", max_sort_rows)):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise CsvqlError(f"{name} must be a positive integer")
    select_all = query.get("select_all", query["select"] == ["*"])
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, strict=True)
            headers = reader.fieldnames
            if not headers:
                raise CsvqlError("CSV file has no header")
            if len(headers) != len(set(headers)):
                raise CsvqlError("CSV header contains duplicate column names")

            columns, analytical = validate_query(query, headers)
            columns.extend(referenced_columns(query["where"]))
            for column in columns:
                if column not in headers:
                    raise CsvqlError(
                        f"Unknown column {column!r}. Available columns: {', '.join(headers)}"
                    )
            limit = query.get("limit")
            if limit == 0:
                return

            def filtered_rows():
                for row in reader:
                    if None in row:
                        raise CsvqlError(f"CSV row ending at line {reader.line_num} has more fields than the header")
                    if matches(row, query["where"]):
                        yield row

            rows = filtered_rows()
            if analytical:
                rows = aggregate_rows(rows, query, max_groups)
            if query.get("order_by"):
                rows = sorted_rows(rows, query["order_by"], max_sort_rows)
            produced = 0
            for row in rows:
                if select_all:
                    yield row
                else:
                    yield {label(item): row[item] for item in query["select"]}
                produced += 1
                if limit is not None and produced >= limit:
                    return
    except OSError as exc:
        raise CsvqlError(f"Cannot read CSV file {str(csv_path)!r}: {exc.strerror}") from exc
    except (UnicodeError, csv.Error) as exc:
        raise CsvqlError(f"Cannot read CSV file {str(csv_path)!r}: {exc}") from exc
