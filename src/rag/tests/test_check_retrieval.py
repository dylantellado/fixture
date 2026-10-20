"""The retrieval check's scoring and output (no ChromaDB needed)."""

import re

from check_retrieval import check_case, format_markdown, load_cases, summarize

CASE = {"name": "1", "user_id": "user_01", "query": "q", "answer": "a", "expected": ["aaa", "bbb"]}


def result(message_id, user_id="user_01"):
    return {"metadata": {"message_id": message_id, "user_id": user_id}}


def test_ranks_and_status():
    checked = check_case(CASE, [result("zzz"), result("bbb"), result("aaa")])
    assert checked["ranks"] == {"aaa": 3, "bbb": 2}
    assert checked["status"] == "all"
    assert checked["other_user_results"] == 0

    assert check_case(CASE, [result("aaa")])["status"] == "some"
    assert check_case(CASE, [result("zzz")])["status"] == "none"
    assert check_case(CASE, [result("zzz")])["ranks"] == {"aaa": None, "bbb": None}


def test_counts_results_from_other_users():
    checked = check_case(CASE, [result("aaa"), result("ccc", user_id="user_02")])
    assert checked["other_user_results"] == 1
    assert summarize([checked])["other_user_results"] == 1


def test_summary_and_markdown():
    checked = [
        check_case(CASE, [result("aaa"), result("bbb")]),
        check_case(CASE, [result("aaa")]),
        check_case(CASE, []),
    ]
    summary = summarize(checked)
    assert summary == {"queries": 3, "all_found": 1, "some_found": 1, "none_found": 1, "other_user_results": 0}

    markdown = format_markdown(checked, summary, 5, {"input_sha256": "abc"})
    assert "1 of 3 queries" in markdown
    assert "| 1 | `user_01` | q | a | 1/2 | 1, – | 0 |" in markdown


def test_committed_cases_are_well_formed():
    cases = load_cases()
    assert len(cases) == 15
    for case in cases:
        assert re.fullmatch(r"user_0[1-4]", case["user_id"])
        assert case["query"] and case["answer"] and case["expected"]
        assert all(re.fullmatch(r"[0-9a-f]{16}", mid) for mid in case["expected"])
