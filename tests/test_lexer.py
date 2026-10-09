import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from csvql.errors import CsvqlError
from csvql.lexer import tokenize
from csvql.parser import parse
from csvql.executor import execute
from csvql.tokens import TokenType

ROOT = Path(__file__).resolve().parents[1]


class LexerExtensionTests(unittest.TestCase):
    def test_operators(self):
        self.assertEqual([t.value for t in tokenize("> >= < <= = !=")[:-1]],
                         [">", ">=", "<", "<=", "=", "!="])

    def test_number_literals(self):
        for literal in ("0", "-12", "3.5", "-0.25", ".5", "-.5"):
            with self.subTest(literal=literal):
                token = tokenize(literal)[0]
                self.assertEqual((token.type, token.value), (TokenType.NUMBER, literal))

    def test_bad_numbers(self):
        for literal in ("-", ".", "1.2.3", "1.", "12abc", "--1"):
            with self.subTest(literal=literal), self.assertRaises(CsvqlError):
                tokenize(literal)

    def test_quoted_names_and_strings(self):
        for source, kind, value in (
            ('"First Name"', TokenType.IDENT, "First Name"),
            ('"SELECT"', TokenType.IDENT, "SELECT"),
            ('"a""b"', TokenType.IDENT, 'a"b'),
            ("'O''Brien'", TokenType.STRING, "O'Brien"),
            ("''", TokenType.STRING, ""),
        ):
            with self.subTest(source=source):
                token = tokenize(source)[0]
                self.assertEqual((token.type, token.value), (kind, value))

    def test_unclosed_quotes(self):
        for sql, label in (("'Pune", "string"), ('"First Name', "quoted identifier"),
                           ("'O''Brien", "string")):
            with self.subTest(sql=sql), self.assertRaisesRegex(CsvqlError, "Unterminated " + label):
                tokenize(sql)

    def test_malformed_operators(self):
        for operator in ("!", "==", "><", "=>", ">=="):
            with self.subTest(operator=operator), self.assertRaises(CsvqlError):
                parse(tokenize(f"SELECT name FROM employees WHERE salary {operator} 10"))

    def test_end_to_end_operators_and_quoted_columns(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "people.csv"
            path.write_text("First Name,Net Pay\nAda,-1.5\nBen,0\nCara,2.5\n")
            for operator, number, expected in (
                (">=", "0", ["Ben", "Cara"]), ("<=", "0", ["Ada", "Ben"]),
                ("!=", "0", ["Ada", "Cara"]), ("=", "-1.5", ["Ada"]),
                (">", ".5", ["Cara"]), ("<", "-.5", ["Ada"]),
            ):
                sql = f'SELECT "First Name" FROM people WHERE "Net Pay"{operator}{number}'
                with self.subTest(sql=sql):
                    rows = execute(parse(tokenize(sql)), path)
                    self.assertEqual([r["First Name"] for r in rows], expected)
            result = subprocess.run([sys.executable, "-B", str(ROOT / "cli.py"),
                'SELECT "First Name" FROM people WHERE "Net Pay" >= 0', str(path)],
                capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "{'First Name': 'Ben'}\n{'First Name': 'Cara'}\n")

    def test_quoted_star_is_a_column(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "stars.csv"
            path.write_text("*,name\n5,Ada\n")
            self.assertEqual(list(execute(parse(tokenize('SELECT "*" FROM stars')), path)), [{"*": "5"}])
            self.assertEqual(list(execute(parse(tokenize('SELECT * FROM stars')), path)), [{"*": "5", "name": "Ada"}])

    def test_unclosed_string_cli(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "cli.py"),
            "SELECT name FROM employees WHERE city = 'Pune", "unused.csv"],
            capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Error: Unterminated string", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
