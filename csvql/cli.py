"""Command-line entry point, shared by csvql, python -m csvql, and cli.py."""
import argparse
from decimal import Decimal
from contextlib import closing
import sys

from csvql import __version__
from csvql.analytics import DEFAULT_MAX_GROUPS, DEFAULT_MAX_SORT_ROWS
from csvql.errors import CsvqlError
from csvql.executor import execute
from csvql.lexer import tokenize
from csvql.parser import parse


def positive_integer(text):
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def main(argv=None):
    arguments = argparse.ArgumentParser(prog="csvql", description="Run a streaming SQL query over a CSV file.")
    arguments.add_argument("--version", action="version", version=f"csvql {__version__}")
    arguments.add_argument("query", help="SQL query (quote it as one shell argument)")
    arguments.add_argument("csv_path", help="CSV file with a header row")
    arguments.add_argument("--max-groups", type=positive_integer, default=DEFAULT_MAX_GROUPS,
                           help="maximum GROUP BY groups (default: %(default)s)")
    arguments.add_argument("--max-sort-rows", type=positive_integer, default=DEFAULT_MAX_SORT_ROWS,
                           help="maximum buffered ORDER BY rows (default: %(default)s)")
    args = arguments.parse_args(argv)
    try:
        query = parse(tokenize(args.query))
        with closing(execute(query, args.csv_path, max_groups=args.max_groups,
                             max_sort_rows=args.max_sort_rows)) as results:
            for row in results:
                print({key: format(value, "f") if isinstance(value, Decimal) else value
                       for key, value in row.items()})
    except CsvqlError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        # A downstream command such as head has stopped reading.
        try:
            sys.stdout.close()
        except BrokenPipeError:
            pass
        return 0
    return 0
