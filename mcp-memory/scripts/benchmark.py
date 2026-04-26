#!/usr/bin/env python3
"""Benchmark script for Mnemonic MCP server.

This script evaluates the performance of the Mnemonic MCP server, including:
- Write throughput (sequential and concurrent)
- Search latency
- Ollama embedding performance (inferred from total operation time)
- Qualitative assessment (recall, precision, token overhead, namespace isolation)

Usage:
    python scripts/benchmark.py                          # defaults to 127.0.0.1:8080
    python scripts/benchmark.py --host 0.0.0.0 --port 9000
    python scripts/benchmark.py --output report.md
    python scripts/benchmark.py --no-cleanup             # keep benchmark data after run
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import Client as FastMCPClient


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
class QualitativeResult:
    name: str
    verdict: str
    details: dict[str, Any]
    score: float = 0.0  # 0.0-1.0 normalized score


@dataclass
class BenchmarkReport:
    timestamp: str
    server_url: str
    scenarios: list[BenchmarkResult] = field(default_factory=list)
    qualitative: list[QualitativeResult] = field(default_factory=list)
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


async def measure_write_latency(client: "FastMCPClient", content: dict[str, Any]) -> float:
    """Measure single write latency in milliseconds."""
    start = time.perf_counter()
    await client.call_tool("memory.write", arguments=content)
    return (time.perf_counter() - start) * 1000


async def run_sequential_writes(client: "FastMCPClient", count: int, size: str = "medium") -> BenchmarkResult:
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


async def run_concurrent_writes(client: "FastMCPClient", count: int, concurrency: int, size: str = "medium") -> BenchmarkResult:
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


async def measure_search_latency(client: "FastMCPClient", query: str) -> float:
    """Measure single search latency in milliseconds."""
    start = time.perf_counter()
    await client.call_tool("memory.search", arguments={"query": query, "namespace": "benchmark", "limit": 10})
    return (time.perf_counter() - start) * 1000


async def run_search_benchmark(client: "FastMCPClient", queries: list[str], runs_per_query: int = 5) -> BenchmarkResult:
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


# ─────────────────────────────────────────────────────────────────────────────
# QUALITATIVE ASSESSMENT TESTS
# ─────────────────────────────────────────────────────────────────────────────

async def run_recall_precision_test(client: "FastMCPClient") -> QualitativeResult:
    """Test recall (can find what's stored) and precision (don't find what isn't)."""
    unique_id = f"RECALL_TEST_{uuid.uuid4().hex[:8]}"
    target_memory = {
        "content": f"{unique_id} - This is a very specific memory about PYTHON PROGRAMMING that should be retrievable.",
        "type": "test",
        "namespace": "benchmark",
        "scope_id": "recall-precision-test",
        "source": "benchmark",
        "tags": ["recall-test", "python"],
    }
    write_result = await client.call_tool("memory.write", arguments=target_memory)
    memory_id = write_result.data["record"]["id"]

    # Write distracting memories
    for i in range(5):
        await client.call_tool("memory.write", arguments={
            "content": f"Distractor memory {i} about JavaScript, cooking, sports, etc.",
            "type": "test", "namespace": "benchmark",
            "scope_id": "recall-precision-test", "source": "benchmark",
        })

    # Test 1: Exact unique ID search
    exact_search = await client.call_tool("memory.search", arguments={
        "query": unique_id, "namespace": "benchmark", "limit": 10,
    })
    exact_found = memory_id in [item["id"] for item in exact_search.data["items"]]

    # Test 2: Semantic search for "python programming"
    semantic_search = await client.call_tool("memory.search", arguments={
        "query": "python programming", "namespace": "benchmark", "limit": 5,
    })
    positions = {item["id"]: i for i, item in enumerate(semantic_search.data["items"])}
    target_rank = positions.get(memory_id, 999)
    in_top_3 = target_rank < 3

    # Test 3: Precision - unrelated search should NOT find target
    noise_search = await client.call_tool("memory.search", arguments={
        "query": "aerospace engineering spacecraft", "namespace": "benchmark", "limit": 10,
    })
    noise_found_target = memory_id in [item["id"] for item in noise_search.data["items"]]

    score = 0.0
    if exact_found:
        score += 0.4
    if in_top_3:
        score += 0.3
    if not noise_found_target:
        score += 0.3

    verdict = "EXCELLENT" if score >= 0.9 else "GOOD" if score >= 0.6 else "POOR"

    return QualitativeResult(
        name="Recall & Precision",
        verdict=verdict,
        score=score,
        details={
            "exact_match_found": exact_found,
            "semantic_rank": target_rank + 1,
            "semantic_in_top_3": in_top_3,
            "false_positive_when_noise": noise_found_target,
            "search_mode": semantic_search.data.get("search_mode", "unknown"),
        }
    )


async def run_context_integration_test(client: "FastMCPClient") -> QualitativeResult:
    """Simulate the actual agent workflow: session start, mid-session write, continuation."""
    namespace = f"agent-workflow-{uuid.uuid4().hex[:6]}"

    # Phase 1: Session start - search for existing context
    initial_search = await client.call_tool("memory.search", arguments={
        "query": "project architecture decisions preferences",
        "namespace": namespace, "limit": 5,
    })
    phase1_results = len(initial_search.data["items"])
    phase1_mode = initial_search.data.get("search_mode", "unknown")

    # Phase 2: Agent makes a decision - write it
    decision_content = f"DECISION: Using PostgreSQL for user data. Rationale: ACID compliance, JSON support, mature ecosystem. Made by agent on 2024-01-15."
    write_result = await client.call_tool("memory.write", arguments={
        "content": decision_content,
        "type": "decision",
        "namespace": namespace,
        "scope_id": "agent-session-1",
        "source": "agent",
        "tags": ["#decision", "#architecture"],
        "metadata": {"made_by": "agent", "rationale": "ACID + JSON"},
    })
    decision_id = write_result.data["record"]["id"]

    # Phase 3: Later session - retrieve the decision
    retrieval = await client.call_tool("memory.search", arguments={
        "query": "postgresql decision architecture",
        "namespace": namespace,
        "limit": 5,
    })
    decision_found = decision_id in [item["id"] for item in retrieval.data["items"]]
    decision_rank = next(
        (i for i, item in enumerate(retrieval.data["items"]) if item["id"] == decision_id),
        999
    ) + 1

    # Phase 4: Measure overhead
    typical_retrieval_tokens = sum(
        len(item.get("content", "")) // 4 + 50
        for item in retrieval.data.get("items", [])[:3]
    )

    score = 0.0
    if decision_found:
        score += 0.5
    if decision_rank <= 2:
        score += 0.3
    if typical_retrieval_tokens < 500:
        score += 0.2

    verdict = "EXCELLENT" if score >= 0.8 else "GOOD" if score >= 0.5 else "POOR"

    return QualitativeResult(
        name="Context Integration",
        verdict=verdict,
        score=score,
        details={
            "phase1_existing_context_found": phase1_results,
            "phase1_search_mode": phase1_mode,
            "phase3_decision_found": decision_found,
            "phase3_decision_rank": decision_rank,
            "phase4_context_overhead_tokens": typical_retrieval_tokens,
            "workflow_practical": decision_found and decision_rank <= 2,
        }
    )


async def run_namespace_isolation_test(client: "FastMCPClient") -> QualitativeResult:
    """Verify that memories in one namespace don't leak into another."""
    ns_a = f"isolation-test-A-{uuid.uuid4().hex[:6]}"
    ns_b = f"isolation-test-B-{uuid.uuid4().hex[:6]}"

    memory_a = {
        "content": "UNIQUE_SECRET_KEY_ABC123XYZ This belongs only to namespace A",
        "type": "test", "namespace": ns_a,
        "scope_id": "isolation", "source": "benchmark",
    }
    result_a = await client.call_tool("memory.write", arguments=memory_a)
    id_a = result_a.data["record"]["id"]

    memory_b = {
        "content": "DIFFERENT_SECRET_KEY_DEF456 This belongs only to namespace B",
        "type": "test", "namespace": ns_b,
        "scope_id": "isolation", "source": "benchmark",
    }
    result_b = await client.call_tool("memory.write", arguments=memory_b)
    id_b = result_b.data["record"]["id"]

    search_in_a = await client.call_tool("memory.search", arguments={
        "query": "SECRET_KEY", "namespace": ns_a, "limit": 10,
    })
    ids_in_a = [item["id"] for item in search_in_a.data["items"]]
    b_found_in_a = id_b in ids_in_a
    a_found_in_a = id_a in ids_in_a

    search_in_b = await client.call_tool("memory.search", arguments={
        "query": "SECRET_KEY", "namespace": ns_b, "limit": 10,
    })
    ids_in_b = [item["id"] for item in search_in_b.data["items"]]
    a_found_in_b = id_a in ids_in_b
    b_found_in_b = id_b in ids_in_b

    isolated = not b_found_in_a and not a_found_in_b
    score = 1.0 if isolated else 0.0
    verdict = "PASS" if isolated else "FAIL"

    return QualitativeResult(
        name="Namespace Isolation",
        verdict=verdict,
        score=score,
        details={
            "namespace_A_isolated": not b_found_in_a,
            "namespace_B_isolated": not a_found_in_b,
            "cross_namespace_leakage": b_found_in_a or a_found_in_b,
        }
    )


async def run_reliability_test(client: "FastMCPClient", concurrent_ops: int = 50) -> QualitativeResult:
    """Test reliability under concurrent load."""
    errors = []
    successes = 0
    ids_written = []

    async def write_with_error_handling(index: int) -> tuple[bool, str]:
        try:
            result = await client.call_tool("memory.write", arguments={
                "content": f"Reliability test memory {index}",
                "type": "test", "namespace": "benchmark",
                "scope_id": "reliability-test", "source": "benchmark",
            })
            return True, result.data["record"]["id"]
        except Exception as e:
            return False, str(e)

    tasks = [write_with_error_handling(i) for i in range(concurrent_ops)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, Exception):
            errors.append(str(r))
        elif isinstance(r, tuple):
            success, result = r
            if success:
                successes += 1
                ids_written.append(result)
            else:
                errors.append(result)

    # Sample retrieval check
    retrieval_failures = 0
    for memory_id in ids_written[:10]:
        try:
            get_result = await client.call_tool("memory.get", arguments={"id": memory_id})
            if get_result.data.get("error"):
                retrieval_failures += 1
        except Exception:
            retrieval_failures += 1

    error_rate = len(errors) / concurrent_ops
    score = 1.0 - error_rate
    verdict = "RELIABLE" if error_rate == 0 else "DEGRADED" if error_rate < 0.1 else "UNRELIABLE"

    return QualitativeResult(
        name="Reliability Under Load",
        verdict=verdict,
        score=score,
        details={
            "total_ops": concurrent_ops,
            "successes": successes,
            "errors": len(errors),
            "error_rate_pct": round(error_rate * 100, 2),
            "retrieval_failures_sample": retrieval_failures,
        }
    )


async def run_ollama_bottleneck_analysis(client: "FastMCPClient") -> QualitativeResult:
    """Determine if Ollama is the bottleneck by analyzing timing across content sizes."""
    sizes = {
        "tiny": 50,
        "small": 200,
        "medium": 500,
        "large": 1000,
    }

    results = {}

    for size_name, char_count in sizes.items():
        content = "Test content for embedding analysis. " * (char_count // 30)

        # Warm-up
        await client.call_tool("memory.write", arguments={
            "content": content[:50], "type": "test", "namespace": "benchmark",
            "scope_id": "ollama-analysis", "source": "benchmark",
        })

        latencies = []
        for _ in range(3):
            start = time.perf_counter()
            await client.call_tool("memory.write", arguments={
                "content": content, "type": "test", "namespace": "benchmark",
                "scope_id": "ollama-analysis", "source": "benchmark",
            })
            latencies.append((time.perf_counter() - start) * 1000)

        results[size_name] = {
            "chars": char_count,
            "avg_ms": round(statistics.mean(latencies), 2),
            "stddev_ms": round(statistics.stdev(latencies) if len(latencies) > 1 else 0, 2),
        }

    # Analyze: estimate embedding vs overhead ratio
    large = results.get("large")
    tiny = results.get("tiny")
    bottleneck_verdict = "UNKNOWN"
    est_embedding_pct = 0

    if large and tiny:
        chars_diff = large["chars"] - tiny["chars"]
        ms_diff = large["avg_ms"] - tiny["avg_ms"]
        if chars_diff > 0:
            ms_per_char = ms_diff / chars_diff
            est_overhead = large["avg_ms"] - (ms_per_char * large["chars"])
            est_embedding_pct = min((ms_per_char * large["chars"]) / large["avg_ms"] * 100, 95)
            bottleneck_verdict = "OLLAMA" if est_embedding_pct > 60 else "PROTOCOL"

    score = est_embedding_pct / 100.0 if est_embedding_pct > 0 else 0.5
    verdict = f"OLLAMA bottleneck ({int(est_embedding_pct)}%)" if est_embedding_pct > 60 else f"Balanced ({int(est_embedding_pct)}% embedding)"

    return QualitativeResult(
        name="Ollama Bottleneck Analysis",
        verdict=verdict,
        score=score,
        details={
            "timing_by_size": results,
            "est_embedding_pct": f"{int(est_embedding_pct)}%",
            "bottleneck_verdict": bottleneck_verdict,
        }
    )


def estimate_token_overhead() -> QualitativeResult:
    """Estimate real token cost for an agent session using memory MCP."""
    operation_costs = {
        "search": {"overhead_tokens": 30, "avg_result_chars": 200},
        "write": {"overhead_tokens": 50, "avg_content_chars": 500},
    }

    scenario = {
        "session_start_search": 1,
        "mid_session_writes": 5,
        "session_end_summary": 1,
        "context_compression": 2,
    }

    total_tokens = 0
    breakdown = {}

    for op, count in scenario.items():
        cost_type = "search" if "search" in op else "write"
        cost = operation_costs[cost_type]
        chars = cost["avg_result_chars"] if cost_type == "search" else cost["avg_content_chars"]
        tokens = count * (cost["overhead_tokens"] + chars // 4)
        breakdown[op] = {"count": count, "tokens_each": tokens // count, "tokens_total": tokens}
        total_tokens += tokens

    context_window_tokens = 8192
    overhead_percentage = (total_tokens / context_window_tokens) * 100

    verdict = "LOW" if overhead_percentage < 5 else "MEDIUM" if overhead_percentage < 15 else "HIGH"
    score = 1.0 if overhead_percentage < 5 else 0.7 if overhead_percentage < 15 else 0.3

    return QualitativeResult(
        name="Token Overhead",
        verdict=f"{verdict} ({overhead_percentage:.1f}% of 8K window)",
        score=score,
        details={
            "total_tokens_per_session": total_tokens,
            "context_window_8k_percentage": round(overhead_percentage, 2),
            "breakdown": breakdown,
        }
    )


async def cleanup_benchmark_data(client: "FastMCPClient") -> int:
    """Delete all benchmark memories using delete_by_tag. Returns count of deleted records."""
    delete_result = await client.call_tool("memory.delete_by_tag", arguments={
        "tag": "#benchmark",
    })
    deleted = delete_result.data.get("deleted_count", 0) if hasattr(delete_result, "data") else 0
    return deleted


# ─────────────────────────────────────────────────────────────────────────────
# REPORT GENERATION
# ─────────────────────────────────────────────────────────────────────────────

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

    # Quantitative results
    lines.extend(["", "## Performance Results", ""])

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
    lines.extend(["", "## Performance Summary", ""])
    lines.append("| Scenario | Ops/sec | Avg Latency | Errors |")
    lines.append("|----------|---------|-------------|--------|")
    for r in report.scenarios:
        lines.append(f"| {r.scenario} | {r.ops_per_second:.2f} | {r.avg_latency_ms:.2f}ms | {r.errors} |")

    # Qualitative results
    if report.qualitative:
        lines.extend(["", "## Qualitative Assessment", ""])

        for q in report.qualitative:
            verdict_icon = "✅" if q.score >= 0.8 else "⚠️" if q.score >= 0.5 else "❌"
            lines.append(f"### {verdict_icon} {q.name} — {q.verdict}")
            lines.append("")
            for key, value in q.details.items():
                if isinstance(value, dict):
                    lines.append(f"- **{key}:**")
                    for sub_key, sub_val in value.items():
                        lines.append(f"  - {sub_key}: {sub_val}")
                else:
                    lines.append(f"- **{key}:** {value}")
            lines.append("")

        # Overall qualitative score
        avg_score = sum(q.score for q in report.qualitative) / len(report.qualitative)
        overall_verdict = "EXCELLENT" if avg_score >= 0.8 else "GOOD" if avg_score >= 0.5 else "NEEDS IMPROVEMENT"
        lines.extend(["", f"## Overall Qualitative Score: {overall_verdict} ({avg_score:.0%})", ""])

        lines.extend(["", "## Qualitative Summary", ""])
        lines.append("| Assessment | Verdict | Score |")
        lines.append("|------------|---------|-------|")
        for q in report.qualitative:
            lines.append(f"| {q.name} | {q.verdict} | {q.score:.0%} |")

    lines.extend(["", "---", "*Generated by benchmark.py*"])
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN BENCHMARK RUNNER
# ─────────────────────────────────────────────────────────────────────────────

async def run_benchmark(host: str, port: int, output_path: str | None = None, cleanup: bool = True) -> int:
    """Run all benchmarks and generate report."""
    from fastmcp import Client

    server_url = f"http://{host}:{port}/sse"
    print(f"Connecting to MCP server at {server_url}...")

    try:
        async with Client(server_url) as client:
            print("Connected.")

            # Gather system info
            try:
                health = await client.call_tool("memory.health", arguments={})
                system_info = {"Server Health": str(health)[:80]}
            except Exception as e:
                system_info = {"Server Health": f"Failed: {e}"}

            report = BenchmarkReport(timestamp=datetime.now().isoformat(), server_url=server_url, system_info=system_info)

            # ── Performance Scenarios ────────────────────────────────────
            perf_scenarios = [
                ("Sequential Writes (100)", run_sequential_writes(client, count=100, size="medium")),
                ("Sequential Writes (500)", run_sequential_writes(client, count=500, size="medium")),
                ("Concurrent Writes (100, c=10)", run_concurrent_writes(client, count=100, concurrency=10, size="medium")),
                ("Concurrent Writes (500, c=20)", run_concurrent_writes(client, count=500, concurrency=20, size="medium")),
                ("Search (5 queries x 5 runs)", run_search_benchmark(client, queries=[
                    "benchmark", "content test", "benchmark benchmark", "test performance", "#benchmark"
                ], runs_per_query=5)),
            ]

            print("\n=== Performance Benchmarks ===")
            for name, coro in perf_scenarios:
                print(f"\nRunning: {name}...")
                try:
                    result = await coro
                    report.scenarios.append(result)
                    print(f"  Done: {result.count} ops, {result.ops_per_second:.2f} ops/sec, {result.avg_latency_ms:.2f}ms avg")
                except Exception as e:
                    print(f"  Failed: {e}")

            # ── Qualitative Scenarios ────────────────────────────────────
            # Each entry is (name, coro or result)
            _qual_raw = [
                ("Recall & Precision", run_recall_precision_test(client)),
                ("Context Integration", run_context_integration_test(client)),
                ("Namespace Isolation", run_namespace_isolation_test(client)),
                ("Reliability Under Load", run_reliability_test(client, concurrent_ops=50)),
                ("Ollama Bottleneck Analysis", run_ollama_bottleneck_analysis(client)),
                ("Token Overhead", estimate_token_overhead()),
            ]

            print("\n=== Qualitative Assessment ===")
            for name, coro in _qual_raw:
                print(f"\nRunning: {name}...")
                try:
                    if asyncio.iscoroutine(coro):
                        result = await coro
                    else:
                        result = coro  # already evaluated (e.g. estimate_token_overhead)
                    report.qualitative.append(result)
                    print(f"  Done: {result.verdict} (score: {result.score:.0%})")
                except Exception as e:
                    print(f"  Failed: {e}")

            # ── Cleanup ───────────────────────────────────────────────────
            if cleanup:
                print("\n=== Cleaning up benchmark data ===")
                try:
                    deleted = await cleanup_benchmark_data(client)
                    print(f"  Deleted {deleted} benchmark memories")
                except Exception as e:
                    print(f"  Cleanup failed: {e}")

            markdown_report = generate_report(report)

    except Exception as e:
        print(f"ERROR: Failed to connect: {e}")
        return 1

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
    parser.add_argument("--no-cleanup", dest="cleanup", action="store_false", help="Keep benchmark data after run")
    args = parser.parse_args()
    return asyncio.run(run_benchmark(args.host, args.port, args.output, args.cleanup))


if __name__ == "__main__":
    raise SystemExit(main())
