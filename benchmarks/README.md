# Measured benchmark — 2026-10-08

Environment: Python 3.11.15; macOS-27.0.1-arm64-arm-64bit.

Command:

```bash
python3 -B benchmarks/benchmark.py --rows 10000 100000 500000 --output benchmarks/results.json
```

Query: `SELECT id, department, salary FROM generated WHERE salary >= 0`.

| Rows | File MB | Mode | Seconds | Rows/second | Peak process RSS MB |
|---:|---:|---|---:|---:|---:|
| 10,000 | 0.239 | streaming | 0.0095 | 1,047,134 | 22.68 |
| 10,000 | 0.239 | materialized | 0.0100 | 998,295 | 26.66 |
| 100,000 | 2.489 | streaming | 0.0955 | 1,046,644 | 22.74 |
| 100,000 | 2.489 | materialized | 0.0997 | 1,002,563 | 62.06 |
| 500,000 | 12.889 | streaming | 0.4747 | 1,053,235 | 22.76 |
| 500,000 | 12.889 | materialized | 0.5063 | 987,520 | 221.81 |

MB uses decimal units (1,000,000 bytes). Raw measurements are in [results.json](results.json).

These measurements were rerun after Step 8. They measure ordinary filtering,
not grouping or sorting.

## Method and limits

- Each case runs in a fresh Python subprocess. Input generation is excluded.
- Streaming counts and discards results; materialized mode calls `list()` on the same engine, retaining every result. This is not a historical-version comparison.
- Every row matches. Results are not printed during timing. Query parsing and imports precede the timer.
- Peak RSS includes the interpreter and imported modules, not just query allocations.
- One run per case, in streaming-then-materialized order; no statistical confidence intervals. Files were just generated and may be served by the OS cache. Timing includes execution and file reads, not process startup.
- Memory tracing was disabled. `--trace` adds allocation measurements but changes timing.
- This sample demonstrates the memory cost of retaining results as row counts grow. It does not establish cold-disk throughput or support a claim about files larger than RAM.
- To explore larger inputs, pass larger row counts. Materialized mode may exhaust RAM; choose sizes appropriate for your machine.
- RSS collection is supported on macOS/Linux; unsupported platforms report null.
