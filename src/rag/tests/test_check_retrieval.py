"""The retrieval check's scoring, splits, experiment log and output (no ChromaDB needed)."""

import json
import re

import pytest

import check_retrieval
from check_retrieval import (
    append_experiment_rows,
    assign_splits,
    cases_for_split,
    check_case,
    experiment_row,
    format_markdown,
    index_stats,
    load_case_file,
    load_cases,
    summarize,
)

CASE = {"name": "1", "split": "dev", "user_id": "user_01", "query": "q", "answer": "a", "expected": ["aaa", "bbb"]}


def result(message_id, user_id="user_01"):
    return {"metadata": {"message_id": message_id, "user_id": user_id}}


def test_ranks_status_and_reciprocal_rank():
    checked = check_case(CASE, [result("zzz"), result("bbb"), result("aaa")])
    assert checked["ranks"] == {"aaa": 3, "bbb": 2}
    assert checked["status"] == "full"
    assert checked["reciprocal_rank"] == 1 / 2  # the first expected message is at rank 2
    assert checked["other_user_results"] == 0

    assert check_case(CASE, [result("aaa")])["status"] == "partial"
    missed = check_case(CASE, [result("zzz")])
    assert missed["status"] == "miss"
    assert missed["ranks"] == {"aaa": None, "bbb": None}
    assert missed["reciprocal_rank"] == 0.0


def test_counts_results_from_other_users():
    checked = check_case(CASE, [result("aaa"), result("ccc", user_id="user_02")])
    assert checked["other_user_results"] == 1
    assert summarize([checked])["other_user_results"] == 1


def test_summary_metrics():
    checked = [
        check_case(CASE, [result("aaa"), result("bbb")]),  # 2 of 2, first at rank 1
        check_case(CASE, [result("zzz"), result("aaa")]),  # 1 of 2, first at rank 2
        check_case(CASE, []),  # 0 of 2
    ]
    summary = summarize(checked)
    assert summary["queries"] == 3
    # Recall counts every expected message once: 3 found of 6 expected.
    assert summary["recall"] == pytest.approx(3 / 6)
    assert summary["mrr"] == pytest.approx((1 + 1 / 2 + 0) / 3)
    assert (summary["full"], summary["partial"], summary["miss"]) == (1, 1, 1)
    assert summary["other_user_results"] == 0


def test_assign_splits_is_seeded_and_order_independent():
    names = [f"c{i}" for i in range(20)]
    splits = assign_splits(names, seed=7, test_size=5)
    assert sorted(splits) == sorted(names)
    assert sum(s == "test" for s in splits.values()) == 5
    assert assign_splits(list(reversed(names)), seed=7, test_size=5) == splits
    assert assign_splits(names, seed=8, test_size=5) != splits


def test_cases_for_split():
    cases = [{**CASE, "name": "a", "split": "dev"}, {**CASE, "name": "b", "split": "test"}]
    assert [c["name"] for c in cases_for_split(cases, "dev")] == ["a"]
    assert [c["name"] for c in cases_for_split(cases, "test")] == ["b"]
    assert len(cases_for_split(cases, "all")) == 2


def test_committed_cases_are_well_formed():
    cases = load_cases()
    assert len(cases) >= 45
    # The 15 original example queries from docs/data/corpus_notes.md are all kept.
    assert sum(c["origin"] == "corpus_notes" for c in cases) == 15
    assert len({c["name"] for c in cases}) == len(cases)
    for case in cases:
        assert re.fullmatch(r"user_0[1-4]", case["user_id"])  # never the frozen eval users
        assert case["query"] and case["answer"] and case["expected"]
        assert case["split"] in ("dev", "test")
        assert all(re.fullmatch(r"[0-9a-f]{16}", mid) for mid in case["expected"])
        assert len(set(case["expected"])) == len(case["expected"])


def test_committed_splits_match_the_seed():
    """Nobody can move a case between dev and test without changing the seed."""
    case_file = load_case_file()
    cases = case_file["cases"]
    expected = assign_splits([c["name"] for c in cases], case_file["split_seed"], case_file["test_size"])
    assert {c["name"]: c["split"] for c in cases} == expected


def test_expected_messages_belong_to_the_cases_user():
    """Checked against the pipeline output when it exists (it's git-ignored)."""
    path = check_retrieval.config.DATA_DIR / "processed" / "messages.jsonl"
    if not path.exists():
        pytest.skip("data/processed/messages.jsonl not built; run ingest and preprocess")
    owners = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            message = json.loads(line)
            owners[message["message_id"]] = message["user_id"]
    for case in load_cases():
        for mid in case["expected"]:
            assert owners.get(mid) == case["user_id"], (case["name"], mid)


class FakeCollection:
    def __init__(self, count, metadata):
        self._count, self.metadata = count, metadata

    def count(self):
        return self._count


def test_index_stats():
    stats = index_stats([
        FakeCollection(10, {"embedding_model": "m", "chunks_over_token_limit": 1}),
        FakeCollection(5, {"embedding_model": "m", "chunks_over_token_limit": 0}),
    ])
    assert stats == {"chunks": 15, "over_limit": 1, "embedding_model": "m"}
    # Collections built without token counts can't say.
    assert index_stats([FakeCollection(3, {"embedding_model": "m"})])["over_limit"] == "n/a"


def test_experiment_log_is_created_then_appended(tmp_path):
    path = tmp_path / "rag_experiments.md"
    summary = summarize([check_case(CASE, [result("aaa"), result("bbb")])])
    stats = {"chunks": 12, "over_limit": 0, "embedding_model": "m"}
    row = experiment_row("baseline", "dev", summary, stats, "abc1234", "2026-11-09")
    assert row == "| baseline | m | dev | 1 | 1.000 | 1.000 | 1 | 0 | 0 | 0 | 12 | 0 | `abc1234` | 2026-11-09 |"

    append_experiment_rows([row], path)
    append_experiment_rows([row.replace("dev", "test")], path)
    text = path.read_text()
    assert text.count("| Variant |") == 1  # header written once
    assert text.splitlines()[-2:] == [row, row.replace("dev", "test")]


def test_markdown_lists_every_query_and_split():
    checked = [
        check_case(CASE, [result("aaa"), result("bbb")]),
        check_case({**CASE, "name": "2", "split": "test"}, [result("aaa")]),
    ]
    summaries = {"dev": summarize(checked[:1]), "test": summarize(checked[1:])}
    stats = {"chunks": 2, "over_limit": 0, "embedding_model": "m"}
    markdown = format_markdown(checked, summaries, 5, {"input_sha256": "abc", "embedding_model": "m"}, stats)
    assert "| dev | 1 | 1.000 | 1.000 | 1 | 0 | 0 | 0 |" in markdown
    assert "| test | 1 | 0.500 | 1.000 | 0 | 1 | 0 | 0 |" in markdown
    assert "| 1 | dev | `user_01` | q | a | 2/2 | 1, 2 | 0 |" in markdown
    assert "| 2 | test | `user_01` | q | a | 1/2 | 1, – | 0 |" in markdown



def test_markdown_compares_original_queries_and_lists_experiments():
    original = check_case({**CASE, "ms2_result": "0/2 (–, –)"}, [result("aaa"), result("bbb")])
    added = check_case({**CASE, "name": "n01"}, [])
    summaries = {"dev": summarize([original, added])}
    stats = {"chunks": 2, "over_limit": 0, "embedding_model": "m"}
    experiments = ["| Variant | Split |", "|---|---|", "| 1. Baseline | dev |"]
    markdown = format_markdown([original, added], summaries, 5, {}, stats, experiments)
    assert "| 1 | dev | `user_01` | q | 0/2 (–, –) | 2/2 | 1, 2 |" in markdown
    # Only the original queries go in the comparison table.
    comparison = markdown.split("## The 15 original queries")[1].split("## All queries")[0]
    assert "n01" not in comparison
    assert markdown.rstrip().endswith("| 1. Baseline | dev |")


def test_every_original_query_has_its_milestone_2_result():
    for case in load_cases():
        assert bool(case.get("ms2_result")) == (case["origin"] == "corpus_notes"), case["name"]


def test_experiment_table_reads_only_table_lines(tmp_path):
    path = tmp_path / "log.md"
    path.write_text("# Title\n\nSome text.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert check_retrieval.experiment_table(path) == ["| a | b |", "|---|---|", "| 1 | 2 |"]
    assert check_retrieval.experiment_table(tmp_path / "missing.md") == []
