import unittest
from decimal import Decimal

from csvql.errors import CsvqlError
from csvql.lexer import tokenize
from csvql.parser import parse


class ParserKeywordTests(unittest.TestCase):
    def test_valid_projection_without_where(self):
        self.assertEqual(parse(tokenize("SELECT name, salary FROM employees")), {
            "select": ["name", "salary"], "select_all": False, "from": "employees", "where": None,
        })

    def test_valid_case_insensitive_keywords(self):
        for sql in (
            "SELECT * FROM employees WHERE salary > 400000",
            "select * from employees where salary > 400000",
            "SeLeCt * FrOm employees WhErE salary > 400000",
        ):
            with self.subTest(sql=sql):
                self.assertEqual(parse(tokenize(sql)), {
                    "select": ["*"], "select_all": True, "from": "employees",
                    "where": ("salary", ">", Decimal("400000")),
                })

    def test_select_required(self):
        for first in ("FROM", "WHERE", "name"):
            with self.subTest(first=first), self.assertRaisesRegex(CsvqlError, "Expected SELECT"):
                parse(tokenize(f"{first} name FROM employees"))

    def test_from_required(self):
        for middle in ("SELECT", "WHERE", "employees"):
            with self.subTest(middle=middle), self.assertRaisesRegex(CsvqlError, "Expected FROM"):
                parse(tokenize(f"SELECT name {middle} employees"))

    def test_where_required_before_condition(self):
        for keyword in ("SELECT", "FROM"):
            with self.subTest(keyword=keyword), self.assertRaisesRegex(CsvqlError, "Expected WHERE"):
                parse(tokenize(f"SELECT name FROM employees {keyword} salary > 0"))

    def test_truncated_queries_rejected(self):
        for sql in ("", "SELECT", "SELECT name", "SELECT name FROM",
                    "SELECT name FROM employees WHERE", "SELECT name FROM employees WHERE salary",
                    "SELECT name FROM employees WHERE salary >"):
            with self.subTest(sql=sql), self.assertRaises(CsvqlError):
                parse(tokenize(sql))

    def test_trailing_tokens_and_missing_where_rejected(self):
        for sql in (
            "SELECT name FROM employees extra",
            "SELECT name FROM employees salary > 0",
            "SELECT name FROM employees WHERE salary > 0 WHERE salary < 10",
        ):
            with self.subTest(sql=sql), self.assertRaises(CsvqlError):
                parse(tokenize(sql))


if __name__ == "__main__":
    unittest.main()
