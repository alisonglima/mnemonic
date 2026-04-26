#!/usr/bin/env python3
"""Benchmark script for Mnemonic MCP server.

This script evaluates the performance of the Mnemonic MCP server, including:
- Write throughput (sequential and concurrent)
- Search latency
- Ollama embedding performance (inferred from total operation time)

Usage:
    python scripts/benchmark.py                          # defaults to 127.0.0.1:8080
    python scripts/benchmark.py --host 0.0.0.0 --port 9000
    python scripts/benchmark.py --output report.md
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp import Client as MCPClient


@dataclass
class BenchmarkResult:
    scenario: str
    operation: str
    count: int
    duration_seconds: float
    ops_per_second: float
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    stddev_ms: float
    errors: int = 0
    notes: str = ""


@dataclass
class BenchmarkReport:
    timestamp: str
    server_url: str
    scenarios: list[BenchmarkResult] = field(default_factory=list)
    system_info: dict[str, str] = field(default_factory=dict)


def generate_content(index: int, size: str = "medium") -> dict[str, Any]:
    """Generate benchmark content of specified size.

    Args:
        index: Content index for uniqueness
        size: 'small' (~50 chars), 'medium' (~300 chars), 'large' (~2000 chars)

    Returns:
        Dictionary with content fields for memory.write
    """
    templates = {
        "small": f"Benchmark content {index} - short text for latency testing.",
        "medium": f"Benchmark content {index} - This is a medium-sized text for testing write throughput and search performance across the Mnemonic MCP server. " * 3,
        "large": f"Benchmark content {index} - " + "Lorem ipsum dolor sit amet consectetur adipiscing elit. " * 50,
    }
    return {
        "content": templates.get(size, templates["medium"]),
        "type": "benchmark",
        "namespace": "benchmark",
        "scope_id": f"benchmark-{index // 100}",
        "source": "benchmark-script",
        "tags": [f"bench-{index % 10}", "#benchmark"],
    }


async def measure_write_latency(client: "MCPClient", content: dict[str, Any]) -> float:
    """Measure single write latency in milliseconds."""
    start = time.perf_counter()
    await client.call_tool("memory.write", arguments=content)
    return (time.perf_counter() - start) * 1000


async def run_sequential_writes(client: "MCPClient", count: int, size: str = "medium") -> BenchmarkResult:
    """Run sequential writes and measure performance."""
    latencies = []
    errors = 0

    for i in range(count):
        try:
            latency = await measure_write_latency(client, generate_content(i, size))
            latencies.append(latency)
        except Exception:
            errors += 1

    if not latencies:
        raise RuntimeError("All writes failed")

    duration = sum(latencies) / 1000
    return BenchmarkResult(
        scenario="write_sequential",
        operation="write",
        count=len(latencies),
        duration_seconds=duration,
        ops_per_second=len(latencies) / duration if duration > 0 else 0,
        avg_latency_ms=statistics.mean(latencies),
        min_latency_ms=min(latencies),
        max_latency_ms=max(latencies),
        stddev_ms=statistics.stdev(latencies) if len(latencies) > 1 else 0,
        errors=errors,
        notes=f"size={size}"
    )


async def run_concurrent_writes(client: "MCPClient", count: int, concurrency: int, size: str = "medium") -> BenchmarkResult:
    """Run concurrent writes and measure performance."""
    semaphore = asyncio.Semaphore(concurrency)
    latencies = []
    errors = 0

    async def write_one(index: int) -> float:
        async with semaphore:
            return await measure_write_latency(client, generate_content(index, size))

    start = time.perf_counter()
    results = await asyncio.gather(*[write_one(i) for i in range(count)], return_exceptions=True)
    duration = time.perf_counter() - start

    for r in results:
        if isinstance(r, Exception):
            errors += 1
        else:
            latencies.append(r)

    return BenchmarkResult(
        scenario="write_concurrent",
        operation="write",
        count=count,
        duration_seconds=duration,
        ops_per_second=count / duration if duration > 0 else 0,
        avg_latency_ms=statistics.mean(latencies) if latencies else 0,
        min_latency_ms=min(latencies) if latencies else 0,
        max_latency_ms=max(latencies) if latencies else 0,
        stddev_ms=statistics.stdev(latencies) if len(latencies) > 1 else 0,
        errors=errors,
        notes=f"concurrency={concurrency}, size={size}"
    )


async def measure_search_latency(client: "MCPClient", query: str) -> float:
    """Measure single search latency in milliseconds."""
    start = time.perf_counter()
    await client.call_tool("memory.search", arguments={"query": query, "namespace": "benchmark", "limit": 10})
    return (time.perf_counter() - start) * 1000


async def run_search_benchmark(client: "MCPClient", queries: list[str], runs_per_query: int = 5) -> BenchmarkResult:
    """Run search benchmark with multiple queries."""
    latencies = []
    errors = 0

    for query in queries:
        for _ in range(runs_per_query):
            try:
                latencies.append(await measure_search_latency(client, query))
            except Exception:
                errors += 1

    if not latencies:
        return BenchmarkResult(
            scenario="search", operation="search", count=0,
            duration_seconds=0, ops_per_second=0,
            avg_latency_ms=0, min_latency_ms=0, max_latency_ms=0, stddev_ms=0,
            errors=errors, notes="All searches failed"
        )

    duration = sum(latencies) / 1000
    return BenchmarkResult(
        scenario="search",
        operation="search",
        count=len(latencies),
        duration_seconds=duration,
        ops_per_second=len(latencies) / duration if duration > 0 else 0,
        avg_latency_ms=statistics.mean(latencies),
        min_latency_ms=min(latencies),
        max_latency_ms=max(latencies),
        stddev_ms=statistics.stdev(latencies) if len(latencies) > 1 else 0,
        errors=errors,
        notes=f"queries={len(queries)}, runs_per_query={runs_per_query}"
    )


def generate_report(report: BenchmarkReport) -> str:
    """Generate Markdown report from benchmark results."""
    lines = [
        f"# Mnemonic MCP Benchmark Report",
        f"",
        f"**Generated:** {report.timestamp}",
        f"**Server:** {report.server_url}",
        f"",
        f"## System Information",
        "",
    ]
    for k, v in report.system_info.items():
        lines.append(f"- **{k}:** {v}")

    lines.extend(["", "## Results", ""])

    for scenario in ["write_sequential", "write_concurrent", "search"]:
        results = [r for r in report.scenarios if r.scenario == scenario]
        if not results:
            continue
        lines.append(f"### {scenario.replace('_', ' ').title()}")
        lines.append("")
        for r in results:
            lines.append(f"- **Count:** {r.count} | **Duration:** {r.duration_seconds:.3f}s | **Ops/sec:** {r.ops_per_second:.2f}")
            lines.append(f"  Avg: {r.avg_latency_ms:.2f}ms | Min: {r.min_latency_ms:.2f}ms | Max: {r.max_latency_ms:.2f}ms | Stddev: {r.stddev_ms:.2f}ms | Errors: {r.errors}")
            if r.notes:
                lines.append(f"  Notes: {r.notes}")
            lines.append("")

    # Quick comparison table
    lines.extend(["", "## Quick Comparison", ""])
    lines.append("| Scenario | Ops/sec | Avg Latency | Errors |")
    lines.append("|----------|---------|-------------|--------|")
    for r in report.scenarios:
        lines.append(f"| {r.scenario} | {r.ops_per_second:.2f} | {r.avg_latency_ms:.2f}ms | {r.errors} |")

    lines.extend(["", "---", "*Generated by benchmark.py*"])
    return "\n".join(lines)


async def run_benchmark(host: str, port: int, output_path: str | None = None) -> int:
    """Run all benchmarks and generate report."""
    from mcp import Client as MCPClient

    server_url = f"http://{host}:{port}"
    print(f"Connecting to MCP server at {server_url}...")

    client = MCPClient(server_url)
    try:
        await client.connect()
        print("Connected.")
    except Exception as e:
        print(f"ERROR: Failed to connect: {e}")
        return 1

    # Gather system info
    try:
        health = await client.call_tool("memory.health", arguments={})
        system_info = {"Server Health": str(health)[:80]}
    except Exception as e:
        system_info = {"Server Health": f"Failed: {e}"}

    report = BenchmarkReport(timestamp=datetime.now().isoformat(), server_url=server_url, system_info=system_info)

    scenarios = [
        ("Sequential Writes (100)", run_sequential_writes(client, count=100, size="medium")),
        ("Sequential Writes (500)", run_sequential_writes(client, count=500, size="medium")),
        ("Concurrent Writes (100, c=10)", run_concurrent_writes(client, count=100, concurrency=10, size="medium")),
        ("Concurrent Writes (500, c=20)", run_concurrent_writes(client, count=500, concurrency=20, size="medium")),
        ("Search (5 queries x 5 runs)", run_search_benchmark(client, queries=[
            "benchmark", "content test", "benchmark benchmark", "test performance", "#benchmark"
        ], runs_per_query=5)),
    ]

    for name, coro in scenarios:
        print(f"\nRunning: {name}...")
        try:
            result = await coro
            report.scenarios.append(result)
            print(f"  Done: {result.count} ops, {result.ops_per_second:.2f} ops/sec, {result.avg_latency_ms:.2f}ms avg")
        except Exception as e:
            print(f"  Failed: {e}")

    await client.disconnect()

    markdown_report = generate_report(report)
    print("\n" + "=" * 60)
    print(markdown_report)
    print("=" * 60)

    if output_path:
        try:
            with open(output_path, "w") as f:
                f.write(markdown_report)
            print(f"\nReport written to: {output_path}")
        except Exception as e:
            print(f"\nWarning: Failed to write report: {e}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Mnemonic MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--output", "-o", help="Output Markdown report path")
    args = parser.parse_args()
    return asyncio.run(run_benchmark(args.host, args.port, args.output))


if __name__ == "__main__":
    raise SystemExit(main())