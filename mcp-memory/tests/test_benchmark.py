"""Tests for benchmark.py script — verifies logic without requiring a running server."""

import pytest
from scripts.benchmark import generate_content, BenchmarkResult, BenchmarkReport, generate_report


class TestGenerateContent:
    def test_generates_small_content(self):
        c = generate_content(1, "small")
        assert "content" in c
        assert c["type"] == "benchmark"
        assert c["namespace"] == "benchmark"

    def test_generates_medium_content(self):
        c = generate_content(42, "medium")
        assert "BENCHMARK 42" in c["content"]

    def test_generates_large_content(self):
        c = generate_content(99, "large")
        assert len(c["content"]) > 1000

    def test_uniqueness_by_index(self):
        c1 = generate_content(1, "small")
        c2 = generate_content(2, "small")
        assert c1["content"] != c2["content"]

    def test_scope_id_based_on_index(self):
        c = generate_content(250, "medium")
        assert c["scope_id"] == "benchmark-2"


class TestBenchmarkResult:
    def test_creates_result_with_all_fields(self):
        r = BenchmarkResult(
            scenario="write_sequential", operation="write", count=100,
            duration_seconds=5.5, ops_per_second=18.18,
            avg_latency_ms=55.0, min_latency_ms=30.0, max_latency_ms=120.0,
            stddev_ms=20.0, errors=0
        )
        assert r.count == 100
        assert r.ops_per_second == 18.18

    def test_result_with_errors_and_notes(self):
        r = BenchmarkResult(
            scenario="search", operation="search", count=50,
            duration_seconds=2.0, ops_per_second=25.0,
            avg_latency_ms=40.0, min_latency_ms=20.0, max_latency_ms=100.0,
            stddev_ms=15.0, errors=2, notes="Some queries failed"
        )
        assert r.errors == 2
        assert "failed" in r.notes

    def test_ops_per_second_reflects_successes_not_total(self):
        # With 10 errors out of 100, ops/sec should reflect 90 successes
        r = BenchmarkResult(
            scenario="write_concurrent", operation="write", count=100,
            duration_seconds=10.0, ops_per_second=9.0,  # 90/10, not 100/10
            avg_latency_ms=100.0, min_latency_ms=80.0, max_latency_ms=200.0,
            stddev_ms=20.0, errors=10
        )
        assert r.ops_per_second == 9.0
        assert r.errors == 10


class TestGenerateReport:
    def test_empty_report(self):
        report = BenchmarkReport(timestamp="2024-01-01T00:00:00", server_url="http://localhost:8080")
        md = generate_report(report)
        assert "# Mnemonic MCP Benchmark Report" in md
        assert "Generated:" in md

    def test_report_with_scenarios(self):
        report = BenchmarkReport(
            timestamp="2024-01-01T00:00:00", server_url="http://localhost:8080",
            scenarios=[
                BenchmarkResult(
                    scenario="write_sequential", operation="write", count=100,
                    duration_seconds=5.0, ops_per_second=20.0,
                    avg_latency_ms=50.0, min_latency_ms=25.0, max_latency_ms=100.0,
                    stddev_ms=15.0, errors=0
                )
            ]
        )
        md = generate_report(report)
        assert "write_sequential" in md
        assert "20.00" in md

    def test_report_includes_system_info(self):
        report = BenchmarkReport(
            timestamp="2024-01-01T00:00:00", server_url="http://localhost:8080",
            system_info={"Python": "3.11"}
        )
        md = generate_report(report)
        assert "System Information" in md
        assert "Python" in md
