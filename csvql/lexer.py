# Turns SQL into tokens. Single quotes delimit text; double quotes delimit names.
import re

from csvql.errors import CsvqlError
from csvql.tokens import Token, TokenType

KEYWORDS = {"SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "LIMIT", "GROUP", "BY", "ORDER", "ASC", "DESC", "COUNT", "SUM", "AVG", "MIN", "MAX"}
NUMBER = re.compile(r"-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")


def tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue

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

        if ch in "0123456789-.":
            match = NUMBER.match(text, i)
            if match is None:
                raise CsvqlError(f"Invalid number at position {i}")
            end = match.end()
            if end < n and (text[end].isalnum() or text[end] in "_."):
                raise CsvqlError(f"Invalid number at position {i}")
            tokens.append(Token(TokenType.NUMBER, match.group()))
            i = end
            continue

        if ch in ("'", '"'):
            quote, start = ch, i
            i += 1
            value = []
            while i < n:
                if text[i] == quote:
                    # SQL escapes a quote by doubling it: 'O''Brien'.
                    if i + 1 < n and text[i + 1] == quote:
                        value.append(quote)
                        i += 2
                        continue
                    i += 1
                    break
                value.append(text[i])
                i += 1
            else:
                label = "string" if quote == "'" else "quoted identifier"
                raise CsvqlError(f"Unterminated {label} at position {start}")
            token_type = TokenType.STRING if quote == "'" else TokenType.IDENT
            tokens.append(Token(token_type, "".join(value)))
            continue

        # Match two-character operators before their one-character prefixes.
        if text[i:i + 2] in (">=", "<=", "!="):
            tokens.append(Token(TokenType.OPERATOR, text[i:i + 2]))
            i += 2
            continue
        if ch in "><=":
            tokens.append(Token(TokenType.OPERATOR, ch))
            i += 1
            continue
        punctuation = {"(": TokenType.LPAREN, ")": TokenType.RPAREN, ";": TokenType.SEMICOLON}
        if ch in punctuation:
            tokens.append(Token(punctuation[ch], ch))
            i += 1
            continue
        if ch == ",":
            tokens.append(Token(TokenType.COMMA, ch))
            i += 1
            continue
        if ch == "*":
            tokens.append(Token(TokenType.STAR, ch))
            i += 1
            continue
        raise CsvqlError(f"Unexpected character {ch!r} at position {i}")

    tokens.append(Token(TokenType.EOF, None))
    return tokens
