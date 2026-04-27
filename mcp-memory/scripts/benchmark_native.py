#!/usr/bin/env python3
"""Native write path benchmark — bypasses HTTP/SSE overhead."""
import statistics
import time
from pathlib import Path

from mcp_memory.database import Database
from mcp_memory.repository import MemoryRepository


def benchmark_native_write(count: int = 200) -> None:
    db = Database(Path("/tmp/bench_native.db"))
    db.initialize()
    repo = MemoryRepository(db)

    latencies = []
    for i in range(count):
        start = time.perf_counter()
        repo.create_memory(
            content=f"Native benchmark {i} — medium content for testing. " * 5,
            type="benchmark",
            namespace="bench",
            scope_id="native",
            source="benchmark",
        )
        latencies.append((time.perf_counter() - start) * 1000)

    print(f"Native write path — {count} writes")
    print(f"  Avg:    {statistics.mean(latencies):.2f}ms")
    print(f"  Median: {statistics.median(latencies):.2f}ms")
    print(f"  Min:    {min(latencies):.2f}ms")
    print(f"  Max:    {max(latencies):.2f}ms")
    print(f"  Stddev: {statistics.stdev(latencies):.2f}ms")
    print(f"  p95:    {sorted(latencies)[int(count * 0.95)]:.2f}ms")


if __name__ == "__main__":
    benchmark_native_write()
