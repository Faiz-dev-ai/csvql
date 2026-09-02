# executor.py
# Takes a structured query (from the parser) and actually runs it
# against a real CSV file, row by row.

import csv


def matches(row, condition):
    """
    Checks whether a single row satisfies the WHERE condition.
    condition is a tuple: (column, operator, value)
    row is a dict: {"name": "Arjun", "salary": "450000", ...}
    """
    if condition is None:
        return True  # no WHERE clause -> every row passes

    column, operator, value = condition
    row_value = row[column]

    # Try to compare as numbers if both sides look numeric.
    # This handles the "450000" vs "300000" string-comparison trap.
    try:
        row_value_num = float(row_value)
        value_num = float(value)
        row_value, value = row_value_num, value_num
    except ValueError:
        # Not numeric (e.g. comparing city names) - compare as plain strings
        pass

    if operator == ">":
        return row_value > value
    elif operator == "<":
        return row_value < value
    elif operator == "=":
        return row_value == value
    else:
        raise ValueError(f"Unknown operator: {operator}")


def execute(query, csv_path):
    """
    Runs the structured query against the CSV file at csv_path.
    Returns a list of dicts - the matching rows, with only the requested columns.
    """
    results = []

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)  # each row becomes a dict: {column: value}

        for row in reader:
            if matches(row, query["where"]):
                if query["select"] == ["*"]:
                    results.append(row)
                else:
                    # Pick out only the requested columns, in the requested order
                    results.append({col: row[col] for col in query["select"]})

    return results