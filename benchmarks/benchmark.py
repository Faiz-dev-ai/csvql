"""Reproducible scan benchmark; each measurement runs in a fresh process.

Generation is outside measurement. Materialized mode retains the same engine's
results as a list; it is not a benchmark of a historical CSVQL implementation.
"""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from csvql.executor import execute
from csvql.lexer import tokenize
from csvql.parser import parse

SQL = "SELECT id, department, salary FROM generated WHERE salary >= 0"


def measure(path, mode, trace=False):
    query = parse(tokenize(SQL))
    if trace:
        tracemalloc.start()
    start = time.perf_counter()
    if mode == "materialized":
        results = list(execute(query, path))
        count = len(results)
    else:
        count = sum(1 for _ in execute(query, path))
    elapsed = time.perf_counter() - start
    peak = tracemalloc.get_traced_memory()[1] if trace else None
    if trace:
        tracemalloc.stop()
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_bytes = rss if sys.platform == "darwin" else rss * 1024
    except ImportError:
        rss_bytes = None
    return {"mode": mode, "rows": count, "seconds": elapsed,
            "rows_per_second": count / elapsed, "peak_rss_bytes": rss_bytes,
            "peak_traced_bytes": peak, "tracing_enabled": trace}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", nargs="+", type=int, default=[10000, 100000, 500000])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=["streaming", "materialized"], default="streaming")
    parser.add_argument("--trace", action="store_true", help="Measure Python allocations (adds timing overhead)")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(measure(args.worker, args.mode, args.trace)))
        return
    if any(count <= 0 for count in args.rows):
        parser.error("row counts must be positive")
    results = []
    with tempfile.TemporaryDirectory(prefix="csvql-benchmark-") as temp:
        path = Path(temp) / "generated.csv"
        for count in args.rows:
            with path.open("w", encoding="utf-8", newline="") as f:
                f.write("id,department,salary\n")
                for index in range(count):
                    f.write(f"{index},Engineering,{300000 + index % 100000}\n")
            size = path.stat().st_size
            for mode in ("streaming", "materialized"):
                command = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(path), "--mode", mode]
                if args.trace:
                    command.append("--trace")
                result = subprocess.run(command, check=True, capture_output=True, text=True)
                record = json.loads(result.stdout)
                if record["rows"] != count:
                    raise RuntimeError("Benchmark returned an unexpected row count")
                record["file_bytes"] = size
                results.append(record)
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "query": SQL, "results": results}
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
