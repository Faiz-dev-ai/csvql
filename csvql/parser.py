"""Recursive-descent SELECT parser: comparisons, NOT, AND, then OR."""
from decimal import Decimal

from csvql.ast import Aggregate, Boolean, Comparison, Negation, Order
from csvql.errors import CsvqlError
from csvql.tokens import TokenType

AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
MAX_EXPRESSION_DEPTH = 128


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current(self):
        return self.tokens[self.pos]

    def expect(self, type_):
        tok = self.current()
        if tok.type != type_:
            raise CsvqlError(f"Expected {type_} but got {tok.type} ({tok.value!r})")
        self.pos += 1
        return tok

    def is_keyword(self, keyword):
        tok = self.current()
        return tok.type == TokenType.KEYWORD and tok.value == keyword

    def expect_keyword(self, keyword):
        tok = self.current()
        if not self.is_keyword(keyword):
            raise CsvqlError(f"Expected {keyword} but got {tok.type} ({tok.value!r})")
        self.pos += 1
        return tok

    def parse(self):
        self.expect_keyword("SELECT")
        select_all = self.current().type == TokenType.STAR
        columns = self.parse_columns()
        self.expect_keyword("FROM")
        table = self.expect(TokenType.IDENT).value
        where = None
        if self.current().type == TokenType.KEYWORD and self.current().value not in {"LIMIT", "GROUP", "ORDER"}:
            self.expect_keyword("WHERE")
            where = self.parse_or()
            self.validate_depth(where)

        query = {"select": columns, "select_all": select_all, "from": table, "where": where}
        if self.is_keyword("GROUP"):
            self.pos += 1
            self.expect_keyword("BY")
            query["group_by"] = self.parse_names()
        if self.is_keyword("ORDER"):
            self.pos += 1
            self.expect_keyword("BY")
            orders = [self.parse_order()]
            while self.current().type == TokenType.COMMA:
                self.pos += 1
                orders.append(self.parse_order())
            query["order_by"] = orders
        if self.is_keyword("LIMIT"):
            self.pos += 1
            literal = self.expect(TokenType.NUMBER).value
            if not literal.isascii() or not literal.isdigit():
                raise CsvqlError("LIMIT must be a non-negative integer")
            try:
                query["limit"] = int(literal)
            except ValueError as exc:
                raise CsvqlError("LIMIT integer is too large") from exc
        if self.current().type == TokenType.SEMICOLON:
            self.pos += 1
        self.expect(TokenType.EOF)
        return query

    def parse_columns(self):
        if self.current().type == TokenType.STAR:
            self.pos += 1
            return ["*"]
        columns = [self.parse_item()]
        while self.current().type == TokenType.COMMA:
            self.pos += 1
            columns.append(self.parse_item())
        return columns

    def parse_item(self):
        token = self.current()
        if token.type == TokenType.KEYWORD and token.value in AGGREGATES:
            self.pos += 1
            self.expect(TokenType.LPAREN)
            if self.current().type == TokenType.STAR:
                if token.value != "COUNT":
                    raise CsvqlError("Only COUNT accepts *")
                self.pos += 1
                column = None
            else:
                column = self.expect(TokenType.IDENT).value
            self.expect(TokenType.RPAREN)
            return Aggregate(token.value, column)
        return self.expect(TokenType.IDENT).value

    def parse_names(self):
        names = [self.expect(TokenType.IDENT).value]
        while self.current().type == TokenType.COMMA:
            self.pos += 1
            names.append(self.expect(TokenType.IDENT).value)
        return names

    def parse_order(self):
        item = self.parse_item()
        descending = self.is_keyword("DESC")
        if self.is_keyword("ASC") or descending:
            self.pos += 1
        return Order(item, descending)

    def parse_or(self):
        node = self.parse_and()
        while self.is_keyword("OR"):
            self.pos += 1
            node = Boolean("OR", node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.is_keyword("AND"):
            self.pos += 1
            node = Boolean("AND", node, self.parse_not())
        return node

    def parse_not(self):
        if self.is_keyword("NOT"):
            self.pos += 1
            return Negation(self.parse_not())
        if self.current().type == TokenType.LPAREN:
            self.pos += 1
            node = self.parse_or()
            self.expect(TokenType.RPAREN)
            return node
        return self.parse_condition()

    def parse_condition(self):
        column = self.expect(TokenType.IDENT).value
        operator = self.expect(TokenType.OPERATOR).value
        if self.current().type == TokenType.NUMBER:
            value = Decimal(self.expect(TokenType.NUMBER).value)
        else:
            value = self.expect(TokenType.STRING).value
        return Comparison(column, operator, value)

    @staticmethod
    def validate_depth(expression):
        pending = [(expression, 1)]
        while pending:
            node, depth = pending.pop()
            if depth > MAX_EXPRESSION_DEPTH:
                raise CsvqlError(f"Expression exceeds maximum depth of {MAX_EXPRESSION_DEPTH}")
            if isinstance(node, Boolean):
                pending.extend(((node.left, depth + 1), (node.right, depth + 1)))
            elif isinstance(node, Negation):
                pending.append((node.operand, depth + 1))


def parse(tokens):
    try:
        return Parser(tokens).parse()
    except RecursionError as exc:
        raise CsvqlError("Expression is nested too deeply") from exc
