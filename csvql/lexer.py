# lexer.py
# Turns a raw SQL string into a list of Token objects.

from csvql.tokens import Token, TokenType

KEYWORDS = {"SELECT", "FROM", "WHERE"}


def tokenize(text):
    tokens = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # 1. Skip whitespace - it has no meaning, it's just a separator
        if ch.isspace():
            i += 1
            continue

        # 2. Letters -> could be a KEYWORD or an IDENT (column/table name)
        if ch.isalpha() or ch == "_":
            start = i
            while i < n and (text[i].isalnum() or text[i] == "_"):
                i += 1
            word = text[start:i]
            if word.upper() in KEYWORDS:
                tokens.append(Token(TokenType.KEYWORD, word.upper()))
            else:
                tokens.append(Token(TokenType.IDENT, word))
            continue

        # 3. Digits -> NUMBER
        if ch.isdigit():
            start = i
            while i < n and text[i].isdigit():
                i += 1
            tokens.append(Token(TokenType.NUMBER, text[start:i]))
            continue

        # 4. Single-quoted string -> STRING
        if ch == "'":
            i += 1  # skip opening quote
            start = i
            while i < n and text[i] != "'":
                i += 1
            value = text[start:i]
            i += 1  # skip closing quote
            tokens.append(Token(TokenType.STRING, value))
            continue

        # 5. Comparison operators
        if ch in "><=":
            tokens.append(Token(TokenType.OPERATOR, ch))
            i += 1
            continue

        # 6. Comma
        if ch == ",":
            tokens.append(Token(TokenType.COMMA, ch))
            i += 1
            continue

        # 7. Star
        if ch == "*":
            tokens.append(Token(TokenType.STAR, ch))
            i += 1
            continue        # 8. Anything else is unexpected - fail loudly instead of silently ignoring it
        raise ValueError(f"Unexpected character {ch!r} at position {i}")

    tokens.append(Token(TokenType.EOF, None))
    return tokens