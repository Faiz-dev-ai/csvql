# tokens.py
# Defines the token types our lexer will produce, and the Token object itself.

class TokenType:
    """
    These are the only kinds of 'words' our language understands.
    Think of these as categories/labels, not values.
    """
    KEYWORD = "KEYWORD"    # SELECT, FROM, WHERE
    IDENT = "IDENT"        # column names, table names -> name, salary, employees
    NUMBER = "NUMBER"      # 300000
    STRING = "STRING"      # 'Bengaluru'
    OPERATOR = "OPERATOR"  # >, <, =
    COMMA = "COMMA"        # ,
    STAR = "STAR"          # *
    EOF = "EOF"            # marks the end of input


class Token:
    """
    A single labelled chunk produced by the lexer.
    Example: Token(TokenType.KEYWORD, "SELECT")
    """
    def __init__(self, type_, value):
        self.type = type_
        self.value = value

    def __repr__(self):
        # This just controls how a Token looks when printed - makes debugging easy.
        return f"Token({self.type}, {repr(self.value)})"