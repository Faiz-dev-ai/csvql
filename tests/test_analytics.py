import io
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from csvql.errors import CsvqlError
from csvql.executor import execute
from csvql.lexer import tokenize
from csvql.parser import parse
from test_streaming_comparisons import CountingFile

ROOT = Path(__file__).resolve().parents[1]


def query(sql):
    return parse(tokenize(sql))


class AnalyticsTests(unittest.TestCase):
    def run_query(self, sql, text, **options):
        with patch("csvql.executor.open", return_value=io.StringIO(text)):
            return list(execute(query(sql), "unused", **options))

    def test_all_global_aggregates(self):
        rows = self.run_query("SELECT COUNT(*), COUNT(value), SUM(value), AVG(value), MIN(value), MAX(value) FROM t",
                              "value\n2\n10\n-3\n")
        self.assertEqual(rows, [{"COUNT(*)": 3, "COUNT(value)": 3, "SUM(value)": Decimal(9),
                                 "AVG(value)": Decimal(3), "MIN(value)": "-3", "MAX(value)": "10"}])

    def test_grouped_results_match_sqlite(self):
        records = [("A", "x", 2), ("A", "x", 10), ("A", "y", 6), ("B", "x", -2), ("B", "x", 4)]
        text = "team,kind,value\n" + "".join(f"{a},{b},{c}\n" for a,b,c in records)
        sql = "SELECT team, kind, COUNT(*), SUM(value), AVG(value), MIN(value), MAX(value) FROM t WHERE value >= 0 GROUP BY team, kind ORDER BY SUM(value) DESC, team ASC LIMIT 2"
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE t(team TEXT, kind TEXT, value INTEGER)")
        connection.executemany("INSERT INTO t VALUES(?,?,?)", records)
        expected = connection.execute(sql).fetchall()
        actual = self.run_query(sql, text)
        normalized = [(row['team'], row['kind'], row['COUNT(*)'], int(row['SUM(value)']),
                       float(row['AVG(value)']), int(row['MIN(value)']), int(row['MAX(value)'])) for row in actual]
        self.assertEqual(normalized, expected)

    def test_group_without_aggregate(self):
        self.assertEqual(self.run_query("SELECT team FROM t GROUP BY team ORDER BY team", "team\nB\nA\nB\n"),
                         [{"team": "A"}, {"team": "B"}])

    def test_order_by_unselected_column(self):
        self.assertEqual(self.run_query("SELECT name FROM t ORDER BY salary DESC LIMIT 2", "name,salary\nAda,2\nBen,10\nCara,3\n"),
                         [{"name": "Ben"}, {"name": "Cara"}])

    def test_order_by_unselected_aggregate(self):
        self.assertEqual(self.run_query("SELECT team FROM t GROUP BY team ORDER BY SUM(value) DESC", "team,value\nA,2\nB,8\nA,3\n"),
                         [{"team": "B"}, {"team": "A"}])

    def test_global_empty_input(self):
        expected = [{"COUNT(*)": 0, "SUM(value)": None, "AVG(value)": None, "MIN(value)": None, "MAX(value)": None}]
        sql = "SELECT COUNT(*), SUM(value), AVG(value), MIN(value), MAX(value) FROM t"
        self.assertEqual(self.run_query(sql, "value\n"), expected)
        self.assertEqual(self.run_query(sql + " WHERE value > 10", "value\n1\n"), expected)
        self.assertEqual(self.run_query("SELECT value, COUNT(*) FROM t GROUP BY value", "value\n"), [])

    def test_missing_empty_and_count(self):
        text = "id,value\na,\nb\nc,2\n"
        self.assertEqual(self.run_query("SELECT COUNT(*), COUNT(value), SUM(value), AVG(value) FROM t", text),
                         [{"COUNT(*)": 3, "COUNT(value)": 2, "SUM(value)": Decimal(2), "AVG(value)": Decimal(2)}])

    def test_all_missing_numeric_inputs(self):
        self.assertEqual(self.run_query("SELECT SUM(value), AVG(value) FROM t", "id,value\na,\nb\n"),
                         [{"SUM(value)": None, "AVG(value)": None}])

    def test_bad_numeric_aggregate_is_clear(self):
        for function in ("SUM", "AVG"):
            with self.subTest(function=function), self.assertRaisesRegex(CsvqlError, "requires numeric values"):
                self.run_query(f"SELECT {function}(value) FROM t", "value\n2\nN/A\n")
        self.assertEqual(self.run_query("SELECT SUM(value) FROM t WHERE value > 0", "value\n2\nN/A\n"), [{"SUM(value)": Decimal(2)}])

    def test_exact_sum_beyond_default_decimal_precision(self):
        text = "value\n999999999999999999999999999999.9\n0.1\n"
        self.assertEqual(self.run_query("SELECT SUM(value) FROM t", text),
                         [{"SUM(value)": Decimal("1000000000000000000000000000000.0")}])
        text = "value\n1000000000000000000000000000000\n-1000000000000000000000000000000\n0.0000000000000000000000000000001\n"
        self.assertEqual(self.run_query("SELECT SUM(value) FROM t", text),
                         [{"SUM(value)": Decimal("0.0000000000000000000000000000001")}])

    def test_average_rounding_is_documented_precision(self):
        self.assertEqual(self.run_query("SELECT AVG(value) FROM t", "value\n1\n0\n0\n"),
                         [{"AVG(value)": Decimal("0.3333333333333333333333333333")}])

    def test_min_max_text_and_mixed_types(self):
        self.assertEqual(self.run_query("SELECT MIN(value), MAX(value) FROM t", "value\nZulu\nAda\n"),
                         [{"MIN(value)": "Ada", "MAX(value)": "Zulu"}])
        self.assertEqual(self.run_query("SELECT MIN(value), MAX(value) FROM t", "value\n10\n2\nZulu\n"),
                         [{"MIN(value)": "2", "MAX(value)": "Zulu"}])

    def test_sort_missing_last_both_directions_and_stable_ties(self):
        text = "id,value\na,10\nb,2\nc\nd,002\ne,Zulu\nf,\n"
        for direction, expected in (("ASC", ["b", "d", "a", "f", "e", "c"]),
                                     ("DESC", ["e", "f", "a", "b", "d", "c"])):
            with self.subTest(direction=direction):
                rows = self.run_query(f"SELECT id FROM t ORDER BY value {direction}", text)
                self.assertEqual([row['id'] for row in rows], expected)

    def test_multi_column_sort_with_mixed_directions(self):
        text = "team,value\nB,1\nA,2\nA,10\nB,8\n"
        rows = self.run_query("SELECT * FROM t ORDER BY team ASC, value DESC", text)
        self.assertEqual([(r['team'],r['value']) for r in rows], [("A","10"),("A","2"),("B","8"),("B","1")])

    def test_group_keys_preserve_text_and_missing(self):
        text = "id,code\na,001\nb,1\nc,\nd\ne,001\n"
        rows = self.run_query("SELECT code, COUNT(*) FROM t GROUP BY code", text)
        self.assertEqual(rows, [{"code":"001","COUNT(*)":2},{"code":"1","COUNT(*)":1},
                                {"code":"","COUNT(*)":1},{"code":None,"COUNT(*)":1}])

    def test_limit_after_aggregate_not_before(self):
        self.assertEqual(self.run_query("SELECT SUM(value) FROM t LIMIT 1", "value\n1\n2\n3\n"), [{"SUM(value)":Decimal(6)}])
        self.assertEqual(self.run_query("SELECT team, SUM(value) FROM t GROUP BY team ORDER BY SUM(value) DESC LIMIT 1",
                                       "team,value\nA,1\nB,3\nA,5\n"), [{"team":"A","SUM(value)":Decimal(6)}])

    def test_limit_zero_validates_without_scan(self):
        source = CountingFile("value\nBAD\n")
        with patch("csvql.executor.open", return_value=source):
            self.assertEqual(list(execute(query("SELECT SUM(value) FROM t ORDER BY SUM(value) LIMIT 0"), "unused")), [])
        self.assertEqual(source.lines_read, 1)
        with self.assertRaises(CsvqlError):
            self.run_query("SELECT SUM(missing) FROM t LIMIT 0", "value\n")

    def test_unknown_columns_in_every_clause(self):
        for sql in ("SELECT SUM(missing) FROM t", "SELECT value FROM t ORDER BY missing",
                    "SELECT COUNT(*) FROM t GROUP BY missing", "SELECT COUNT(*) FROM t ORDER BY SUM(missing)"):
            with self.subTest(sql=sql), self.assertRaisesRegex(CsvqlError, "Unknown column"):
                self.run_query(sql, "value\n")

    def test_invalid_grouped_selections(self):
        for sql in ("SELECT value, SUM(value) FROM t", "SELECT * FROM t GROUP BY value",
                    "SELECT value FROM t GROUP BY team", "SELECT team, COUNT(*) FROM t GROUP BY team ORDER BY value"):
            with self.subTest(sql=sql), self.assertRaises(CsvqlError):
                self.run_query(sql, "team,value\n")

    def test_invalid_aggregate_and_clause_syntax(self):
        for sql in ("SELECT SUM(*) FROM t", "SELECT AVG() FROM t", "SELECT SUM(AVG(value)) FROM t",
                    "SELECT COUNT(value,value) FROM t", "SELECT * FROM t ORDER value",
                    "SELECT * FROM t ORDER BY", "SELECT * FROM t GROUP BY",
                    "SELECT * FROM t LIMIT 1 ORDER BY value", "SELECT * FROM t ORDER BY value GROUP BY value"):
            with self.subTest(sql=sql), self.assertRaises(CsvqlError):
                query(sql)

    def test_quoted_aggregate_argument_and_reserved_names(self):
        self.assertEqual(self.run_query('SELECT "GROUP", SUM("Net Pay") FROM t GROUP BY "GROUP"', 'GROUP,Net Pay\nA,1.5\nA,2.5\n'),
                         [{"GROUP":"A","SUM(Net Pay)":Decimal("4.0")}])
        self.assertEqual(self.run_query('SELECT COUNT(*), COUNT("*") FROM t', 'id,*\na,\nb\n'),
                         [{"COUNT(*)":2,'COUNT("*")':1}])

    def test_duplicate_output_labels_rejected(self):
        for sql in ('SELECT COUNT(*), COUNT(*) FROM t', 'SELECT "COUNT(*)", COUNT(*) FROM t GROUP BY "COUNT(*)"'):
            with self.assertRaisesRegex(CsvqlError, "unique"):
                self.run_query(sql, "COUNT(*)\n1\n")

    def test_group_resource_limit(self):
        text = "team\nA\nB\n"
        with self.assertRaisesRegex(CsvqlError, "GROUP BY exceeded 1"):
            self.run_query("SELECT team, COUNT(*) FROM t GROUP BY team", text, max_groups=1)
        self.assertEqual(len(self.run_query("SELECT team, COUNT(*) FROM t GROUP BY team", text, max_groups=2)),2)

    def test_sort_resource_limit_even_with_limit(self):
        with self.assertRaisesRegex(CsvqlError, "ORDER BY exceeded 1"):
            self.run_query("SELECT * FROM t ORDER BY value LIMIT 1", "value\n2\n1\n", max_sort_rows=1)
        self.assertEqual(self.run_query("SELECT * FROM t ORDER BY value LIMIT 1", "value\n2\n1\n", max_sort_rows=2), [{"value":"1"}])

    def test_resource_options_validated(self):
        for name in ("max_groups", "max_sort_rows"):
            for value in (0, -1, True, 1.5):
                with self.subTest(name=name,value=value), self.assertRaises(CsvqlError):
                    self.run_query("SELECT * FROM t", "value\n", **{name:value})

    def test_file_closes_on_aggregate_failure(self):
        source = io.StringIO("value\nBAD\n")
        with patch("csvql.executor.open", return_value=source):
            with self.assertRaises(CsvqlError):
                list(execute(query("SELECT SUM(value) FROM t"), "unused"))
        self.assertTrue(source.closed)

    def test_file_closes_on_sort_limit(self):
        source = io.StringIO("value\n2\n1\n")
        with patch("csvql.executor.open", return_value=source):
            with self.assertRaises(CsvqlError):
                list(execute(query("SELECT * FROM t ORDER BY value"), "unused", max_sort_rows=1))
        self.assertTrue(source.closed)

    def test_cli_aggregate_format_and_resource_error(self):
        result = subprocess.run([sys.executable,"-B","-m","csvql",
            "SELECT department, COUNT(*), SUM(salary) FROM employees GROUP BY department ORDER BY SUM(salary) DESC LIMIT 1",
            "employees.csv"],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,"{'department': 'Engineering', 'COUNT(*)': 4, 'SUM(salary)': '1425000'}\n")
        result = subprocess.run([sys.executable,"-B","-m","csvql", "--max-sort-rows","1",
            "SELECT name FROM employees ORDER BY salary", "employees.csv"],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,1)
        self.assertIn("ORDER BY exceeded 1",result.stderr)
        self.assertNotIn("Traceback",result.stderr)


if __name__ == '__main__':
    unittest.main()
