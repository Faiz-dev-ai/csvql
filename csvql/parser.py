# parser.py
# Turns a list of Tokens into a structured query dict:
# {"select": [...], "from": "...", "where": (col, op, value) or None}

from csvql.tokens import TokenType


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0  # pointer to the current token, just like `i` in the lexer

    def current(self):
        return self.tokens[self.pos]

    def expect(self, type_):
        """
        The next token MUST be of this type.
        If it is: consume it (move pointer forward) and return it.
        If not: fail loudly with a clear error - don't guess, don't continue.
        """
        tok = self.current()
        if tok.type != type_:
            raise ValueError(f"Expected {type_} but got {tok.type} ({tok.value!r})")
        self.pos += 1
        return tok

    def parse(self):
        self.expect(TokenType.KEYWORD)  # consumes SELECT (we trust it's SELECT - v1 only supports SELECT queries)
        columns = self.parse_columns()
        self.expect(TokenType.KEYWORD)  # consumes FROM
        table = self.expect(TokenType.IDENT).value

        where = None
        # WHERE is optional - only parse it if there are tokens left besides EOF
        if self.current().type == TokenType.KEYWORD:
            self.expect(TokenType.KEYWORD)  # consumes WHERE
            where = self.parse_condition()

        self.expect(TokenType.EOF)  # confirms nothing unexpected is left over
        return {"select": columns, "from": table, "where": where}

    def parse_columns(self):
        """
        Handles: * | name | name, name, name...
        """
        if self.current().type == TokenType.STAR:
            self.pos += 1
            return ["*"]

        columns = [self.expect(TokenType.IDENT).value]
        while self.current().type == TokenType.COMMA:
            self.pos += 1  # consume the comma
            columns.append(self.expect(TokenType.IDENT).value)
        return columns

    def parse_condition(self):
        """
        Handles: column OPERATOR value   (value can be NUMBER or STRING)
        """
        column = self.expect(TokenType.IDENT).value
        operator = self.expect(TokenType.OPERATOR).value

        if self.current().type == TokenType.NUMBER:
            value = self.expect(TokenType.NUMBER).value
        else:
            value = self.expect(TokenType.STRING).value

        return (column, operator, value)


def parse(tokens):
    return Parser(tokens).parse()