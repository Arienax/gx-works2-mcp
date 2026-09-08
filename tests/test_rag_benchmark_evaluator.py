from pathlib import Path

from tools.evaluate_rag_benchmark import _is_release_benchmark


def test_only_canonical_benchmark_updates_release_manifest(tmp_path: Path):
    root = tmp_path
    benchmarks = root / "benchmarks"
    benchmarks.mkdir()

    canonical = benchmarks / "fx3u_rag_benchmark.jsonl"
    custom = benchmarks / "fx3u_rag_benchmark_pre_skill.jsonl"
    canonical.write_text("{}\n", encoding="utf-8")
    custom.write_text("{}\n", encoding="utf-8")

    assert _is_release_benchmark(canonical, root) is True
    assert _is_release_benchmark(custom, root) is False
