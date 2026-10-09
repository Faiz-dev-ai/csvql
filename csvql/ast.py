"""Expression nodes produced by the parser."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import NamedTuple, Union


class Comparison(NamedTuple):
    column: str
    operator: str
    value: Union[Decimal, str]


@dataclass(frozen=True)
class Boolean:
    operator: str
    left: Expression
    right: Expression


@dataclass(frozen=True)
class Negation:
    operand: Expression


Expression = Union[Comparison, Boolean, Negation]


def referenced_columns(expression):
    """Visit all branches, including branches that may short-circuit at runtime."""
    pending = [expression]
    while pending:
        node = pending.pop()
        if isinstance(node, Boolean):
            pending.extend((node.right, node.left))
        elif isinstance(node, Negation):
            pending.append(node.operand)
        elif node is not None:
            yield node[0]


@dataclass(frozen=True)
class Aggregate:
    function: str
    column: str | None  # None is COUNT(*), distinct from a column named "*".

    @property
    def label(self):
        argument = "*" if self.column is None else self.column
        # Distinguish COUNT(*) from COUNT("*") in dictionary output.
        if self.column == "*":
            argument = '"*"'
        return f"{self.function}({argument})"


@dataclass(frozen=True)
class Order:
    item: str | Aggregate
    descending: bool = False
