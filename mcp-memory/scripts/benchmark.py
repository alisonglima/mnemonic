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
    cleanup_deleted: int = 0
    cleanup_method: str = ""


def generate_content(index: int, size: str = "medium") -> dict[str, Any]:
    """Generate benchmark content of specified size.

    Args:
        index: Content index for uniqueness
        size: 'small' (~50 chars), 'medium' (~300 chars), 'large' (~2000 chars)

    Returns:
        Dictionary with content fields for memory.write
    """
    templates = {
        "small": f"BENCHMARK {index} - short text for latency testing.",
        "medium": f"BENCHMARK {index} - This is a medium-sized text for testing write throughput and search performance across the Mnemonic MCP server. " * 3,
        "large": f"BENCHMARK {index} - " + "Lorem ipsum dolor sit amet consectetur adipiscing elit. " * 50,
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

    wall_start = time.perf_counter()
    for i in range(count):
        try:
            latency = await measure_write_latency(client, generate_content(i, size))
            latencies.append(latency)
        except Exception as e:
            errors += 1
            print(f"  Write error [{i}]: {e}")
    duration = time.perf_counter() - wall_start

    if not latencies:
        raise RuntimeError("All writes failed")

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

    for i, r in enumerate(results):
        if isinstance(r, Exception):
            errors += 1
            print(f"  Concurrent write error [{i}]: {r}")
        else:
            latencies.append(r)

    return BenchmarkResult(
        scenario="write_concurrent",
        operation="write",
        count=count,
        duration_seconds=duration,
        # Use successful count so ops/sec isn't inflated when errors occur
        ops_per_second=len(latencies) / duration if duration > 0 else 0,
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

    wall_start = time.perf_counter()
    for query in queries:
        for _ in range(runs_per_query):
            try:
                latencies.append(await measure_search_latency(client, query))
            except Exception as e:
                errors += 1
                print(f"  Search error [{query!r}]: {e}")
    duration = time.perf_counter() - wall_start

    if not latencies:
        return BenchmarkResult(
            scenario="search", operation="search", count=0,
            duration_seconds=0, ops_per_second=0,
            avg_latency_ms=0, min_latency_ms=0, max_latency_ms=0, stddev_ms=0,
            errors=errors, notes="All searches failed"
        )

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
    unique_token = f"RECALL_{uuid.uuid4().hex[:8].upper()}"
    target_memory = {
        "content": f"This memory contains {unique_token} about PYTHON PROGRAMMING and software development that should be retrievable by semantic search.",
        "type": "test",
        "namespace": "benchmark",
        "scope_id": "recall-precision-test",
        "source": "benchmark",
        "tags": ["recall-test", "python"],
    }
    write_result = await client.call_tool("memory.write", arguments=target_memory)
    memory_id = write_result.data["record"]["id"]

    # Write distractors — enough to make top-3 rank meaningful
    for i in range(20):
        await client.call_tool("memory.write", arguments={
            "content": f"Distractor memory {i}: JavaScript frameworks, cooking recipes, football scores, travel destinations, stock market trends.",
            "type": "test", "namespace": "benchmark",
            "scope_id": "recall-precision-test", "source": "benchmark",
        })

    # Wait for Qdrant coverage to recover before measuring search
    for _ in range(60):  # up to 5 minutes
        health = await client.call_tool("memory.health", arguments={})
        coverage = health.data.get("qdrant_coverage_ratio", 0)
        if coverage >= 0.80:
            break
        await asyncio.sleep(5)

    # Test 1: Exact token search (verifies the record is retrievable at all)
    exact_search = await client.call_tool("memory.search", arguments={
        "query": f"{unique_token} python programming", "namespace": "benchmark", "limit": 10,
    })
    exact_found = memory_id in [item["id"] for item in exact_search.data["items"]]

    # Test 2: Semantic search — query phrased differently from content
    semantic_search = await client.call_tool("memory.search", arguments={
        "query": "software engineering best practices", "namespace": "benchmark", "limit": 10,
    })
    positions = {item["id"]: i for i, item in enumerate(semantic_search.data["items"])}
    target_rank = positions.get(memory_id, 999)
    in_top_3 = target_rank < 3

    # Test 3: Precision — unrelated query should NOT surface the target
    noise_search = await client.call_tool("memory.search", arguments={
        "query": "aerospace engineering spacecraft orbital mechanics", "namespace": "benchmark", "limit": 10,
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
            "unique_token": unique_token,
            "distractors": 20,
            "exact_match_found": exact_found,
            "semantic_rank": target_rank + 1,
            "semantic_in_top_3": in_top_3,
            "false_positive_when_noise": noise_found_target,
            "search_mode": semantic_search.data.get("search_mode", "unknown"),
            "_namespaces": ["benchmark"],
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
    today = datetime.now().date().isoformat()
    decision_content = f"DECISION: Using PostgreSQL for user data. Rationale: ACID compliance, JSON support, mature ecosystem. Made by agent on {today}."
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
            "namespace": namespace,
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
            "namespace_A": ns_a,
            "namespace_B": ns_b,
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
            "_namespaces": ["benchmark"],
        }
    )


async def run_ollama_bottleneck_analysis(client: "FastMCPClient") -> QualitativeResult:
    """Estimate where latency is spent by comparing write times across content sizes."""
    SAMPLES_PER_SIZE = 20  # was 3
    WARMUP_RUNS = 5

    # Measure base overhead with minimal content (no FTS/embedding)
    base_latencies = []
    for _ in range(10):
        start = time.perf_counter()
        await client.call_tool("memory.write", arguments={
            "content": "x", "type": "test", "namespace": "bench-base-bottleneck",
            "scope_id": "base", "source": "benchmark",
        })
        base_latencies.append((time.perf_counter() - start) * 1000)
    base_overhead_ms = statistics.median(base_latencies)

    sizes = {"tiny": 50, "small": 200, "medium": 500, "large": 1500}
    results = {}

    for size_name, char_count in sizes.items():
        content = ("Test content. " * (char_count // 14 + 1))[:char_count]

        # Warmup
        for _ in range(WARMUP_RUNS):
            await client.call_tool("memory.write", arguments={
                "content": content, "type": "test", "namespace": "bench-warmup-bottleneck",
                "scope_id": "bottleneck", "source": "benchmark",
            })

        latencies = []
        for _ in range(SAMPLES_PER_SIZE):
            start = time.perf_counter()
            await client.call_tool("memory.write", arguments={
                "content": content, "type": "test", "namespace": "bench-bottleneck",
                "scope_id": "bottleneck", "source": "benchmark",
            })
            latencies.append((time.perf_counter() - start) * 1000)

        net_ms = statistics.median(latencies) - base_overhead_ms
        results[size_name] = {
            "chars": char_count,
            "raw_median_ms": round(statistics.median(latencies), 2),
            "net_ms": round(max(net_ms, 0), 2),
            "stddev_ms": round(statistics.stdev(latencies), 2),
        }

    # Determine if latency scales with content size
    tiny_net = results.get("tiny", {}).get("net_ms", 0)
    large_net = results.get("large", {}).get("net_ms", 0)
    bottleneck_verdict = "FLAT_LATENCY"
    est_embedding_pct = 0

    if large_net > tiny_net:
        chars_diff = sizes["large"] - sizes["tiny"]
        ms_diff = large_net - tiny_net
        if chars_diff > 0:
            ms_per_char = ms_diff / chars_diff
            avg_net = (tiny_net + large_net) / 2
            if avg_net > 0:
                est_embedding_pct = min((ms_per_char * sizes["large"]) / (avg_net + base_overhead_ms) * 100, 95)
                bottleneck_verdict = "EMBEDDING_DOMINANT" if est_embedding_pct > 60 else "OVERHEAD_DOMINANT"

    return QualitativeResult(
        name="Bottleneck Analysis",
        verdict=f"Embedding ~{int(est_embedding_pct)}% of write latency" if est_embedding_pct > 0 else "Latency flat across sizes (overhead dominant)",
        score=est_embedding_pct / 100.0 if est_embedding_pct > 0 else 0.5,
        details={
            "timing_by_size": results,
            "base_overhead_ms": round(base_overhead_ms, 2),
            "est_embedding_pct": f"~{int(est_embedding_pct)}%",
            "bottleneck_verdict": bottleneck_verdict,
            "samples_per_size": SAMPLES_PER_SIZE,
            "_namespaces": ["bench-base-bottleneck", "bench-warmup-bottleneck", "bench-bottleneck"],
        }
    )


async def run_token_overhead_test(client: "FastMCPClient") -> QualitativeResult:
    """Measure ACTUAL token overhead from real searches, not theoretical estimate."""
    namespace = f"token-overhead-{uuid.uuid4().hex[:6]}"

    # Write a known corpus
    for i in range(10):
        await client.call_tool("memory.write", arguments={
            "content": f"Memory {i}: Project context about architecture decisions for the authentication system.",
            "type": "test", "namespace": namespace,
            "scope_id": "token-test", "source": "benchmark",
        })

    # Wait for coverage
    for _ in range(60):
        health = await client.call_tool("memory.health", arguments={})
        coverage = health.data.get("qdrant_coverage_ratio", 0)
        if coverage >= 0.80:
            break
        await asyncio.sleep(5)

    # Run searches
    queries = [
        "authentication architecture",
        "project decisions",
        "system design",
    ]

    search_tokens = []
    for query in queries:
        result = await client.call_tool("memory.search", arguments={
            "query": query, "namespace": namespace, "limit": 5,
        })
        token_estimate = result.data.get("token_estimate", 0)
        item_count = result.data.get("item_count", 0)
        search_tokens.append({"query": query, "tokens": token_estimate, "items": item_count})

    # Measure write tokens
    write_tokens_estimate = 0
    for i in range(5):
        result = await client.call_tool("memory.write", arguments={
            "content": f"Additional memory {i} about security policies.",
            "type": "test", "namespace": namespace,
            "scope_id": "token-test", "source": "benchmark",
        })
        content_len = len(f"Additional memory {i} about security policies.")
        write_tokens_estimate += content_len // 4 + 30  # content + MCP overhead

    total_overhead_tokens = sum(s["tokens"] for s in search_tokens) + write_tokens_estimate
    context_window = 200_000
    overhead_pct = (total_overhead_tokens / context_window) * 100

    verdict = "NEGLIGIBLE" if overhead_pct < 1 else "LOW" if overhead_pct < 5 else "MEDIUM"
    score = 1.0 if overhead_pct < 1 else 0.8 if overhead_pct < 5 else 0.5

    return QualitativeResult(
        name="Token Overhead (measured)",
        verdict=f"{verdict} ({overhead_pct:.2f}% of 200K window)",
        score=score,
        details={
            "search_token_estimates": search_tokens,
            "write_token_estimate": write_tokens_estimate,
            "total_overhead_tokens": total_overhead_tokens,
            "context_window_200k": context_window,
            "context_window_pct": round(overhead_pct, 3),
            "method": "measured (content length / 4 + overhead)",
            "_namespaces": [namespace],
        }
    )


def estimate_token_overhead_theoretical() -> QualitativeResult:
    """Theoretical token cost estimate for an agent session using memory MCP.

    NOTE: All values are fixed estimates, not measured. Use as a rough
    planning guide, not a benchmark result. Run with real agent traces
    for accurate token accounting.
    """
    # Rough estimates per operation type
    operation_costs = {
        "search": {"overhead_tokens": 30, "avg_result_chars": 200},
        "write": {"overhead_tokens": 50, "avg_content_chars": 500},
    }

    # Typical session pattern
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

    # Use a large modern context window as reference (200K tokens)
    context_window_tokens = 200_000
    overhead_percentage = (total_tokens / context_window_tokens) * 100

    verdict = "NEGLIGIBLE" if overhead_percentage < 1 else "LOW" if overhead_percentage < 5 else "MEDIUM"
    score = 1.0 if overhead_percentage < 1 else 0.8 if overhead_percentage < 5 else 0.5

    return QualitativeResult(
        name="Token Overhead (theoretical estimate)",
        verdict=f"{verdict} ({overhead_percentage:.2f}% of 200K window)",
        score=score,
        details={
            "total_tokens_per_session": total_tokens,
            "context_window_200k_percentage": round(overhead_percentage, 3),
            "breakdown": breakdown,
            "note": "Fixed estimates — not measured. Actual overhead depends on content size and result count.",
        }
    )


async def cleanup_benchmark_data(client: "FastMCPClient", extra_namespaces: list[str] | None = None) -> int:
    """Delete all benchmark memories. Returns count of deleted records."""
    deleted = 0

    # Try delete_by_tag first (efficient)
    try:
        delete_result = await client.call_tool("memory.delete_by_tag", arguments={
            "tag": "#benchmark",
        })
        if hasattr(delete_result, "data"):
            deleted = delete_result.data.get("deleted_count", 0)
            if deleted > 0:
                print(f"  Deleted {deleted} via delete_by_tag")
                # Still continue to clean up qualitative namespaces (they may not have #benchmark tag)
    except Exception as e:
        print(f"  delete_by_tag not available: {e}")

    # Fallback: search by content keyword + delete one by one
    if deleted == 0:
        print("  Using fallback cleanup via search+delete...")
        page = 0
        while True:
            search_result = await client.call_tool("memory.search", arguments={
                "query": "BENCHMARK",
                "namespace": "benchmark",
                "limit": 100,
                "include_retracted": True,
            })
            items = search_result.data.get("items", [])
            if not items:
                break

            for item in items:
                try:
                    await client.call_tool("memory.delete", arguments={
                        "id": item["id"],
                        "expected_version": item.get("version", 1),
                        "reason": "benchmark cleanup",
                    })
                    deleted += 1
                except Exception as e:
                    print(f"  Delete error [{item['id']}]: {e}")

            page += 1
            if len(items) < 100 or page > 100:
                break

    # Cleanup qualitative test namespaces by exact name
    qualitative_namespaces = extra_namespaces or []
    qualitative_namespaces += ["benchmark-warmup"]

    for ns in qualitative_namespaces:
        try:
            page = 0
            ns_deleted = 0
            while True:
                search_result = await client.call_tool("memory.search", arguments={
                    "query": "test",
                    "namespace": ns,
                    "limit": 100,
                    "include_retracted": True,
                })
                items = search_result.data.get("items", [])
                if not items:
                    break
                for item in items:
                    try:
                        await client.call_tool("memory.delete", arguments={
                            "id": item["id"],
                            "expected_version": item.get("version", 1),
                            "reason": "benchmark cleanup",
                        })
                        deleted += 1
                        ns_deleted += 1
                    except Exception as e:
                        print(f"  Delete error in ns={ns} [{item['id']}]: {e}")
                page += 1
                if len(items) < 100 or page > 50:
                    break
            if ns_deleted:
                print(f"  Cleaned {ns_deleted} from namespace '{ns}'")
        except Exception as e:
            print(f"  Namespace cleanup failed for '{ns}': {e}")

    print(f"  Total deleted: {deleted}")
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

    # Cleanup report
    lines.extend(["", "## Cleanup", ""])
    lines.append(f"- **Records deleted:** {report.cleanup_deleted}")
    lines.append(f"- **Method:** {report.cleanup_method}")

    lines.extend(["", "---", "*Generated by benchmark.py*"])
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN BENCHMARK RUNNER
# ─────────────────────────────────────────────────────────────────────────────

async def run_benchmark(host: str, port: int, output_path: str | None = None, cleanup: bool = True, recall_only: bool = False, wait_coverage: float | None = None) -> int:
    """Run all benchmarks and generate report."""
    from fastmcp import Client

    server_url = f"http://{host}:{port}/sse"
    print(f"Connecting to MCP server at {server_url}...")

    try:
        async with Client(server_url) as client:
            print("Connected.")

            # Wait for qdrant coverage if requested
            if wait_coverage is not None:
                print(f"Waiting for qdrant coverage >= {wait_coverage:.2f}...")
                deadline = time.time() + 300  # 5 minute timeout
                while time.time() < deadline:
                    health = await client.call_tool("memory.health", arguments={})
                    coverage = health.data.get("qdrant_coverage_ratio", 0.0)
                    if coverage >= wait_coverage:
                        print(f"  Coverage reached: {coverage:.2%}")
                        break
                    print(f"  Coverage: {coverage:.2%}, waiting...")
                    await asyncio.sleep(5)
                else:
                    print(f"  Timeout waiting for coverage (was {coverage:.2%})")
                    return 1

            # Gather system info
            try:
                health = await client.call_tool("memory.health", arguments={})
                system_info = {"Server Health": str(health)[:80]}
            except Exception as e:
                system_info = {"Server Health": f"Failed: {e}"}

            report = BenchmarkReport(timestamp=datetime.now().isoformat(), server_url=server_url, system_info=system_info)

            # Track qualitative namespaces for cleanup
            qualitative_namespaces: list[str] = []

            # ── Performance Scenarios ────────────────────────────────────
            if not recall_only:
                perf_scenarios = [
                    ("Sequential Writes (100)", run_sequential_writes(client, count=100, size="medium")),
                    ("Sequential Writes (500)", run_sequential_writes(client, count=500, size="medium")),
                    ("Concurrent Writes (100, c=10)", run_concurrent_writes(client, count=100, concurrency=10, size="medium")),
                    ("Concurrent Writes (500, c=20)", run_concurrent_writes(client, count=500, concurrency=20, size="medium")),
                    ("Search (5 queries x 5 runs)", run_search_benchmark(client, queries=[
                        "software engineering performance measurement",
                        "distributed systems fault tolerance",
                        "machine learning model training pipeline",
                        "database query optimization index",
                        "API design REST GraphQL microservices",
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
            print("\n=== Qualitative Assessment ===")

            qual_fns = [
                ("Recall & Precision", lambda: run_recall_precision_test(client)),
            ]

            if not recall_only:
                qual_fns.extend([
                    ("Context Integration", lambda: run_context_integration_test(client)),
                    ("Namespace Isolation", lambda: run_namespace_isolation_test(client)),
                    ("Reliability Under Load", lambda: run_reliability_test(client, concurrent_ops=50)),
                    ("Bottleneck Analysis", lambda: run_ollama_bottleneck_analysis(client)),
                    ("Token Overhead (measured)", lambda: run_token_overhead_test(client)),
                    ("Token Overhead (theoretical)", lambda: estimate_token_overhead_theoretical()),
                ])

            for name, fn in qual_fns:
                print(f"\nRunning: {name}...")
                try:
                    coro = fn()
                    if asyncio.iscoroutine(coro):
                        result = await coro
                    else:
                        result = coro
                    report.qualitative.append(result)
                    print(f"  Done: {result.verdict} (score: {result.score:.0%})")

                    # Collect namespaces from qualitative tests for cleanup
                    ns = result.details.get("namespace")
                    if ns:
                        qualitative_namespaces.append(ns)
                    for key in ("namespace_A", "namespace_B"):
                        ns = result.details.get(key)
                        if ns:
                            qualitative_namespaces.append(ns)
                    # Collect benchmark namespaces from _namespaces field
                    extra_ns = result.details.get("_namespaces", [])
                    for ns in extra_ns:
                        if ns not in qualitative_namespaces:
                            qualitative_namespaces.append(ns)
                except Exception as e:
                    print(f"  Failed: {e}")

            # ── Cleanup ───────────────────────────────────────────────────
            report.cleanup_method = "none"
            if cleanup:
                print("\n=== Cleaning up benchmark data ===")
                try:
                    deleted = await cleanup_benchmark_data(client, extra_namespaces=qualitative_namespaces)
                    report.cleanup_deleted = deleted
                    report.cleanup_method = "delete_by_tag + exact_namespace"
                    print(f"  Deleted {deleted} benchmark memories")
                except Exception as e:
                    print(f"  Cleanup failed: {e}")
                    report.cleanup_method = f"error: {e}"

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
    parser.add_argument("--recall-only", action="store_true", help="Only run recall/precision test")
    parser.add_argument("--wait-coverage", type=float, help="Wait until qdrant_coverage_ratio >= threshold before running")
    args = parser.parse_args()
    return asyncio.run(run_benchmark(args.host, args.port, args.output, args.cleanup, args.recall_only, args.wait_coverage))


if __name__ == "__main__":
    raise SystemExit(main())
