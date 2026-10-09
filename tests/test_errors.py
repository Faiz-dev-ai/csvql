import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from csvql.errors import CsvqlError
from csvql.executor import execute
from csvql.lexer import tokenize
from csvql.parser import parse

ROOT = Path(__file__).resolve().parents[1]


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.csv = Path(self.temp.name) / "employees.csv"
        self.csv.write_text("name,salary,city\nArjun,450000,Bengaluru\nPriya,320000,Mumbai\n")

    def query(self, sql):
        return list(execute(parse(tokenize(sql)), self.csv))

    def cli(self, sql, path=None):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "cli.py"), sql, str(path or self.csv)],
            capture_output=True, text=True, cwd=ROOT,
        )

    def test_valid_queries(self):
        self.assertEqual(self.query("SELECT name FROM employees WHERE salary > 400000"), [{"name": "Arjun"}])
        self.assertEqual(self.query("select name from employees where city = 'Mumbai'"), [{"name": "Priya"}])
        self.assertEqual(len(self.query("SELECT * FROM employees")), 2)

    def test_syntax_errors_share_exception(self):
        for sql in ("SELECT @ FROM employees", "SELECT FROM employees", "", "SELECT name FROM"):
            with self.subTest(sql=sql), self.assertRaises(CsvqlError):
                self.query(sql)

    def test_unknown_columns_even_without_matching_rows(self):
        for sql in (
            "SELECT nme FROM employees",
            "SELECT nme FROM employees WHERE salary > 999999",
            "SELECT * FROM employees WHERE missing = 1",
        ):
            with self.subTest(sql=sql), self.assertRaisesRegex(CsvqlError, "Unknown column .*Available columns: name, salary, city"):
                self.query(sql)

    def test_header_only_validates_columns(self):
        self.csv.write_text("name,salary,city\n")
        self.assertEqual(self.query("SELECT name FROM employees"), [])
        for sql in ("SELECT missing FROM employees", "SELECT * FROM employees WHERE missing = 1"):
            with self.subTest(sql=sql), self.assertRaises(CsvqlError):
                self.query(sql)

    def test_empty_file(self):
        self.csv.write_text("")
        with self.assertRaisesRegex(CsvqlError, "no header"):
            self.query("SELECT * FROM employees")

    def test_missing_file(self):
        self.csv.unlink()
        with self.assertRaisesRegex(CsvqlError, "Cannot read CSV file"):
            self.query("SELECT * FROM employees")

    def test_permission_error(self):
        with patch("builtins.open", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaisesRegex(CsvqlError, "Permission denied"):
                self.query("SELECT * FROM employees")

    def test_cli_success(self):
        result = self.cli("SELECT name FROM employees WHERE salary > 400000")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "{'name': 'Arjun'}")
        self.assertEqual(result.stderr, "")

    def test_cli_errors(self):
        for sql, path in (
            ("SELECT nme FROM employees", self.csv),
            ("SELECT @ FROM employees", self.csv),
            ("SELECT FROM employees", self.csv),
            ("SELECT name SELECT employees", self.csv),
            ("FROM name FROM employees", self.csv),
            ("SELECT name FROM employees SELECT salary > 0", self.csv),
            ("SELECT * FROM employees", self.csv.parent / "missing.csv"),
        ):
            with self.subTest(sql=sql, path=path):
                result = self.cli(sql, path)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.startswith("Error: "))
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
