# cli.py
# The command-line entry point: ties lexer -> parser -> executor together.

import sys
from csvql.lexer import tokenize
from csvql.parser import parse
from csvql.executor import execute


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 cli.py \"SQL QUERY\" path/to/file.csv")
        sys.exit(1)

    sql_query = sys.argv[1]
    csv_path = sys.argv[2]

    tokens = tokenize(sql_query)
    query = parse(tokens)
    results = execute(query, csv_path)

    for row in results:
        print(row)


if __name__ == "__main__":
    main()