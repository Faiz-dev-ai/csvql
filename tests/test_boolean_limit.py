import io
from itertools import product
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from csvql.ast import Boolean, Negation
from csvql.errors import CsvqlError
from csvql.executor import evaluate, execute
from csvql.lexer import tokenize
from csvql.parser import parse
from test_streaming_comparisons import CountingFile

ROOT = Path(__file__).resolve().parents[1]


def query(sql):
    return parse(tokenize(sql))


class BooleanLimitTests(unittest.TestCase):
    def test_precedence_and_grouping_against_sqlite(self):
        # Independent oracle over all true/false/unknown combinations.
        expressions = (
            "a = 1 OR b = 1 AND c = 1",
            "(a = 1 OR b = 1) AND c = 1",
            "NOT a = 1 AND b = 1",
            "NOT (a = 1 OR b = 1)",
            "NOT NOT a = 1",
            "a = 1 OR NOT b = 1 AND c = 1",
        )
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        for expression in expressions:
            tree = query("SELECT * FROM data WHERE " + expression)["where"]
            for values in product((0, 1, None), repeat=3):
                row = {key: None if value is None else str(value)
                       for key, value in zip(("a", "b", "c"), values)}
                expected = connection.execute(
                    f"SELECT {expression} FROM (SELECT ? AS a, ? AS b, ? AS c)", values
                ).fetchone()[0]
                with self.subTest(expression=expression, values=values):
                    actual = evaluate(row, tree)
                    self.assertIs(actual, None if expected is None else bool(expected))

    def test_short_circuit_evaluation(self):
        for expression, expected in (("a = 1 OR missing = 1", True),
                                     ("a = 0 AND missing = 1", False)):
            self.assertIs(evaluate({"a": "1"}, query("SELECT * FROM t WHERE " + expression)["where"]), expected)

    def test_validate_all_branches_before_rows(self):
        for expression in ("a = 1 OR missing = 1", "NOT missing = 1", "a = 0 AND missing = 1"):
            source = CountingFile("a\n1\n")
            with patch("csvql.executor.open", return_value=source):
                with self.assertRaisesRegex(CsvqlError, "Unknown column 'missing'"):
                    list(execute(query("SELECT * FROM t WHERE " + expression), "unused"))
            self.assertEqual(source.lines_read, 1)

    def test_not_does_not_include_missing_or_invalid_numeric_values(self):
        source = io.StringIO("id,value\na,\nb,N/A\nc\nd,0\ne,2\n")
        with patch("csvql.executor.open", return_value=source):
            rows = execute(query("SELECT id FROM t WHERE NOT value > 1"), "unused")
            self.assertEqual(list(rows), [{"id": "d"}])

    def test_limit_counts_matches_and_stops_before_next_row(self):
        source = CountingFile("name,value\nAda,0\nBen,1\nCara,2\nBAD,EXTRA,ROW\n")
        with patch("csvql.executor.open", return_value=source):
            rows = execute(query("SELECT name FROM t WHERE value > 0 LIMIT 2"), "unused")
            self.assertEqual(list(rows), [{"name": "Ben"}, {"name": "Cara"}])
        self.assertEqual(source.lines_read, 4)
        self.assertTrue(source.closed)

    def test_limit_zero_validates_header_without_reading_data(self):
        source = CountingFile("name\nAda\n")
        with patch("csvql.executor.open", return_value=source):
            self.assertEqual(list(execute(query("SELECT * FROM t LIMIT 0"), "unused")), [])
        self.assertEqual(source.lines_read, 1)
        self.assertTrue(source.closed)
        with patch("csvql.executor.open", return_value=io.StringIO("name\n")):
            with self.assertRaises(CsvqlError):
                list(execute(query("SELECT missing FROM t LIMIT 0"), "unused"))

    def test_limit_without_where_and_beyond_end(self):
        for limit, expected in ((1, 1), (100, 2)):
            with patch("csvql.executor.open", return_value=io.StringIO("name\nAda\nBen\n")):
                self.assertEqual(len(list(execute(query(f"SELECT * FROM t LIMIT {limit};"), "unused"))), expected)

    def test_no_matches_with_limit(self):
        with patch("csvql.executor.open", return_value=io.StringIO("a\n0\n")):
            self.assertEqual(list(execute(query("SELECT * FROM t WHERE a = 1 LIMIT 2"), "unused")), [])

    def test_invalid_limits(self):
        for suffix in ("-1", "1.5", "'2'", "", "2 LIMIT 3", "2 WHERE a = 1", ".5", "-0"):
            with self.subTest(suffix=suffix), self.assertRaises(CsvqlError):
                query("SELECT * FROM t LIMIT " + suffix)

    def test_invalid_expressions(self):
        for expression in ("", "()", "NOT", "a = 1 AND", "OR a = 1", "(a = 1",
                           "a = 1)", "a = 1 OR OR b = 2", "(a = 1 LIMIT 2)"):
            with self.subTest(expression=expression), self.assertRaises(CsvqlError):
                query("SELECT * FROM t WHERE " + expression)

    def test_one_optional_terminal_semicolon(self):
        self.assertEqual(query("SELECT * FROM t;"), query("SELECT * FROM t"))
        for sql in ("SELECT * FROM t;;", "SELECT * FROM t; SELECT * FROM t"):
            with self.assertRaises(CsvqlError):
                query(sql)

    def test_new_keywords_can_be_quoted_column_names(self):
        with patch("csvql.executor.open", return_value=io.StringIO("AND,LIMIT\nyes,1\n")):
            rows = execute(query('select "AND" from t where "LIMIT" = 1 limit 1'), "unused")
            self.assertEqual(list(rows), [{"AND": "yes"}])

    def test_deep_expressions_fail_cleanly(self):
        for expression in ("NOT " * 200 + "a = 1", "(" * 500 + "a = 1" + ")" * 500,
                           " OR ".join(["a = 1"] * 200)):
            with self.assertRaises(CsvqlError):
                query("SELECT * FROM t WHERE " + expression)

    def test_module_cli_combined_query(self):
        result = subprocess.run([sys.executable, "-B", "-m", "csvql",
            "SELECT name FROM employees WHERE salary >= 300000 AND (city = 'Bengaluru' OR city = 'Pune') AND NOT name = 'Arjun' LIMIT 2;",
            "employees.csv"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "{'name': 'Karthik'}\n{'name': 'Anjali'}\n")

    def test_help_version_and_usage(self):
        for args, code, expected in ((["--help"], 0, "usage:"), (["--version"], 0, "csvql 0.1.0"), ([], 2, "required")):
            result = subprocess.run([sys.executable, "-B", "-m", "csvql", *args], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, code)
            self.assertIn(expected, result.stdout + result.stderr)

    def test_utf8_bom_header(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bom.csv"
            path.write_text("name\nAda\n", encoding="utf-8-sig")
            self.assertEqual(list(execute(query("SELECT name FROM t"), path)), [{"name": "Ada"}])


if __name__ == "__main__":
    unittest.main()
