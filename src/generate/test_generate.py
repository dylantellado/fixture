"""Tests for the generator. No API calls: the writer is faked."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import main  # noqa: E402
from acts import ACTS, FLOWS, answer, check_flows  # noqa: E402
from mess import add_mess  # noqa: E402
from sampler import build_scenario, load_cards, to_annotations, to_source_thread, to_state_record  # noqa: E402
from writer import check_bodies  # noqa: E402

CARDS = load_cards()
USER = CARDS["users"][0]


def fake_bodies(scenario):
    """A draft that uses every required phrase, as a good writer would."""
    return [f"Hi, about our meeting. {' / '.join(s.phrases)}" if s.phrases else "Hi, quick note."
            for s in scenario.steps]


def test_flows_and_cards_are_consistent():
    assert check_flows() == []
    for kind, card in CARDS["counterparts"].items():
        assert set(card["flows"]) <= set(FLOWS), kind
    for user in CARDS["users"]:
        assert set(user["counterparts"]) <= set(CARDS["counterparts"]), user["user_id"]
        assert user["split"] in ("train", "eval")


def test_user_messages_never_need_a_response():
    for act in ACTS:
        assert answer(act, "user")[1] is False  # NR1


def test_key_rule_answers():
    assert answer("still_on", "them")[:2] == ("none", True)  # E13, NR6
    assert answer("restate", "them")[:2] == ("none", False)  # E14, NR7
    assert answer("sched_link", "system")[:2] == ("proposed_times", True)  # E16, NR5
    assert answer("cancel_followup", "them")[:2] == ("reschedule", False)  # NR2
    assert answer("cancel_invite", "them")[:2] == ("reschedule", True)  # NR2
    assert answer("intro_other", "intro")[:2] == ("new_request", False)  # NR10
    assert answer("cold_sales", "them")[:2] == ("none", False)  # E9


def test_scenarios_are_reproducible():
    a = build_scenario(CARDS, USER, 7, seed=1)
    b = build_scenario(CARDS, USER, 7, seed=1)
    c = build_scenario(CARDS, USER, 7, seed=2)
    assert [(s.act, s.phrases, s.sent) for s in a.steps] == [(s.act, s.phrases, s.sent) for s in b.steps]
    assert (a.flow, a.steps[0].sent) != (c.flow, c.steps[0].sent) or a.kind != c.kind


@pytest.mark.parametrize("number", range(1, 80))
def test_scenarios_match_the_data_contract_and_state(number):
    scenario = build_scenario(CARDS, USER, number, seed=2026)
    thread = to_source_thread(scenario, "Subject", fake_bodies(scenario))
    addresses = set(thread["participants"])
    times = [s.sent for s in scenario.steps]
    assert times == sorted(times)
    for message in thread["messages"]:
        assert message["sender"] in addresses
        assert set(message["recipients"]) <= addresses
    # The state agrees with the answers.
    for step in scenario.steps:
        assert step.state["needs_response"] == step.needs_response
        if step.needs_response:
            assert step.state["waiting_on"] == "P0"
        if step.label == "acceptance":
            assert step.state["status"] == "confirmed" and step.state["confirmed"]
            assert step.phrases == [step.state["confirmed"]["quote"]]
        if step.act in ("propose", "propose_one", "reschedule_offer"):
            assert step.phrases and all(p["start"] for p in step.state["proposed"] if p["position"] == step.position)
    assert len(to_annotations(scenario)) == len(scenario.steps)
    assert to_state_record(scenario, "x")["states"][-1]["position"] == len(scenario.steps) - 1


def test_check_bodies_catches_missing_phrases_and_new_times():
    scenario = next(s for n in range(1, 60) if (s := build_scenario(CARDS, USER, n, 2026)).flow == "user_asks")
    good = fake_bodies(scenario)
    assert check_bodies(scenario, "Subject", good) == []
    bad = list(good)
    bad[1] = "Hi, I can do whenever."  # the offer is missing its times
    assert any("missing the exact phrase" in p for p in check_bodies(scenario, "Subject", bad))
    bad = list(good)
    bad[0] = "Could we meet? Maybe 4pm?"  # a request must not offer a time
    assert any("new clock time" in p for p in check_bodies(scenario, "Subject", bad))
    assert check_bodies(scenario, "Subject", good[:-1])  # wrong number of bodies


def test_still_on_must_be_a_question():
    scenario = next(s for n in range(1, 200) if (s := build_scenario(CARDS, USER, n, 2026)).flow == "still_on")
    bodies = fake_bodies(scenario)
    bodies[-1] = "Just confirming our meeting is still on. Let me know if anything changes."
    assert any("as a question" in p for p in check_bodies(scenario, "Subject", bodies))
    bodies[-1] = "Are we still on for this week?"
    assert check_bodies(scenario, "Subject", bodies) == []


def test_mess_is_seeded_and_keeps_the_text():
    scenario = build_scenario(CARDS, USER, 3, 2026)
    bodies = fake_bodies(scenario)
    one, changes = add_mess(scenario, bodies, 2026)
    two, _ = add_mess(scenario, bodies, 2026)
    assert one == two and len(changes) == len(bodies)
    assert all(m.startswith(b) for m, b in zip(one, bodies))


def test_generate_and_assemble_with_a_fake_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA", tmp_path)

    def fake_write(client, scenario, model, effort):
        return {"subject": "Meeting", "bodies": fake_bodies(scenario),
                "usage": {"input_tokens": 1, "output_tokens": 1, "attempts": 1, "model": model}}

    monkeypatch.setattr(main, "write_thread", fake_write)
    monkeypatch.setitem(sys.modules, "anthropic", type(sys)("anthropic"))
    sys.modules["anthropic"].Anthropic = lambda **kw: None
    out = tmp_path / "generated"
    args = ["generate", "--users", "user_05", "user_11", "--threads-per-user", "3", "--out", str(out)]
    assert main.main(args) == 0
    assert len(main.read_jsonl(out / "threads.jsonl")) == 6
    # A second run reuses the cache: the writer is never called.
    monkeypatch.setattr(main, "write_thread", lambda *a: pytest.fail("cache not used"))
    assert main.main(args) == 0

    base = tmp_path / "base"
    base.mkdir()
    (base / "users.json").write_text(json.dumps([{"user_id": "user_01", "name": "A", "email": "a@example.com"}]))
    (base / "generated_threads.jsonl").write_text("")
    (base / "annotations.jsonl").write_text("")
    source = tmp_path / "source"
    assert main.main(["assemble", "--base", str(base), "--generated", str(out), "--out", str(source)]) == 0
    splits = json.loads((source / "splits.json").read_text())
    assert splits == {"train": ["user_01", "user_05"], "eval": ["user_11"]}
    assert [u["user_id"] for u in json.loads((source / "users.json").read_text())] == ["user_01", "user_05", "user_11"]
