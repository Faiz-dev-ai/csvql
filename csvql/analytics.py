"""Aggregation and stable sorting with explicit row/group resource limits."""
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from functools import cmp_to_key

from csvql.ast import Aggregate
from csvql.errors import CsvqlError
from csvql.lexer import NUMBER

DEFAULT_MAX_GROUPS = 100_000
DEFAULT_MAX_SORT_ROWS = 100_000


def label(item):
    return item.label if isinstance(item, Aggregate) else item


def value_key(value):
    """Numbers first, then case-sensitive text; missing is handled separately."""
    if isinstance(value, (Decimal, int)):
        return (0, Decimal(value))
    if NUMBER.fullmatch(value.strip()):
        return (0, Decimal(value.strip()))
    return (1, value)


def exact_add(left, right):
    # Decimal addition normally rounds to the ambient precision (usually 28).
    # Reserve all integer/fraction digits and a carry digit for exact addition.
    exponent = min(left.as_tuple().exponent, right.as_tuple().exponent)
    digits = max(left.adjusted(), right.adjusted()) - exponent + 2
    with localcontext() as context:
        context.prec = max(28, digits)
        return left + right


class Accumulator:
    def __init__(self, aggregate):
        self.aggregate = aggregate
        self.count = 0
        self.total = Decimal(0)
        self.extreme = None
        self.extreme_key = None

    def add(self, row):
        function, column = self.aggregate.function, self.aggregate.column
        value = row[column] if column is not None else None
        if function == "COUNT":
            if column is None or value is not None:
                self.count += 1
            return
        if value is None:
            return
        if function in ("SUM", "AVG"):
            text = value.strip()
            if not text:
                return
            if NUMBER.fullmatch(text) is None:
                raise CsvqlError(f"{self.aggregate.label} requires numeric values; got {value!r}")
            self.total = exact_add(self.total, Decimal(text))
            self.count += 1
            return
        key = value_key(value)
        if (self.extreme_key is None or
                (function == "MIN" and key < self.extreme_key) or
                (function == "MAX" and key > self.extreme_key)):
            self.extreme, self.extreme_key = value, key

    def result(self):
        function = self.aggregate.function
        if function == "COUNT":
            return self.count
        if function == "SUM":
            return self.total if self.count else None
        if function == "AVG":
            if not self.count:
                return None
            with localcontext() as context:
                context.prec = 28
                context.rounding = ROUND_HALF_EVEN
                return self.total / self.count
        return self.extreme


def validate_query(query, headers):
    """Validate analytical semantics and return every referenced source column."""
    selections = query["select"]
    groups = query.get("group_by", [])
    orders = query.get("order_by", [])
    select_all = query.get("select_all", selections == ["*"])
    items = ([] if select_all else selections) + [order.item for order in orders]
    aggregate_query = bool(groups) or any(isinstance(item, Aggregate) for item in items)
    if aggregate_query:
        if select_all:
            raise CsvqlError("SELECT * cannot be combined with grouping or aggregates")
        for item in items:
            if isinstance(item, str) and item not in groups:
                raise CsvqlError(f"Column {item!r} must appear in GROUP BY or an aggregate")
    output_labels = headers if select_all else [label(item) for item in selections]
    if len(output_labels) != len(set(output_labels)):
        raise CsvqlError("Selected output names must be unique")
    columns = list(groups)
    for item in items:
        if isinstance(item, Aggregate):
            if item.column is not None:
                columns.append(item.column)
        else:
            columns.append(item)
    return columns, aggregate_query


def aggregate_rows(rows, query, max_groups):
    """Keep only per-group accumulators, not the input rows."""
    columns = query.get("group_by", [])
    items = query["select"] + [order.item for order in query.get("order_by", [])]
    aggregates = list(dict.fromkeys(item for item in items if isinstance(item, Aggregate)))

    def new_state():
        return {item: Accumulator(item) for item in aggregates}

    # A global aggregate produces one result even with zero input rows.
    groups = {} if columns else {(): new_state()}
    for row in rows:
        key = tuple(row[column] for column in columns)
        if key not in groups:
            if len(groups) >= max_groups:
                raise CsvqlError(f"GROUP BY exceeded {max_groups} groups; increase --max-groups or reduce the query")
            groups[key] = new_state()
        for state in groups[key].values():
            state.add(row)
    for key, states in groups.items():
        record = dict(zip(columns, key))
        record.update({item: state.result() for item, state in states.items()})
        yield record


def sorted_rows(rows, orders, max_rows):
    """Stable multi-key sort, with missing values last in either direction."""
    buffered = []
    for row in rows:
        if len(buffered) >= max_rows:
            raise CsvqlError(f"ORDER BY exceeded {max_rows} rows; increase --max-sort-rows or reduce the query")
        keys = [None if row[order.item] is None else value_key(row[order.item]) for order in orders]
        buffered.append((row, keys))

    def compare(left, right):
        for order, a, b in zip(orders, left[1], right[1]):
            if a is None or b is None:
                result = (a is None) - (b is None)
                if result:
                    return result
            else:
                result = (a > b) - (a < b)
                if result:
                    return -result if order.descending else result
        return 0

    buffered.sort(key=cmp_to_key(compare))
    for row, _ in buffered:
        yield row
