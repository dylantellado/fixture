"""Run the fake scenarios in scenarios/scenarios.json against the real Gemini and
embeddings, and write docs/evidence/ms3/draft_scenarios.md.

Every person, address and event in the scenarios is made up, so the report can
show the drafts in full.

For each scenario the report shows the status, the times offered, accepted or
confirmed, every check, the context used, tokens, latency, cost and the draft.
Two things are verified independently of the pipeline:
  - every offered, accepted or confirmed time in the response is re-checked
    with checker.run_checks (slots.check_time and the text scanner) against
    the scenario's calendar; any failure makes this script exit with code 1
  - the scenario's expectations (status, action, number of offers, the
    accepted time, text that must or must not appear)

Run from src/drafter (needs gcloud application-default credentials; costs about
a cent per scenario):
    GOOGLE_CLOUD_PROJECT=fixture-ac215-96dhbm uv run python run_scenarios.py
    uv run python run_scenarios.py --only prompt_injection --no-write
"""

import argparse
import json
import logging
import os
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "fixture-ac215-96dhbm")

import checker  # noqa: E402
import logs  # noqa: E402
import main  # noqa: E402
import pipeline  # noqa: E402
import slots  # noqa: E402
from rules import rules_for  # noqa: E402
from schemas import DraftRequest  # noqa: E402

HERE = Path(__file__).resolve().parent
SCENARIOS = HERE / "scenarios" / "scenarios.json"
REPORT = HERE.parent.parent / "docs" / "evidence" / "ms3" / "draft_scenarios.md"

# Vertex AI prices per token, from the Cloud Billing catalog (checked 2026-11-09).
# Gemini 3.8 Flash (global): $1.50 / $7.50 per 1M input / output tokens (thinking is billed as
# output), at an introductory half price through 2026-12-31. gemini-embedding-001
# ("Large Text Embedding Model - Predictions"): $0.15 per 1M tokens.
PRICES = {
    "now": {"input": 0.75e-6, "output": 3.75e-6, "embedding": 0.15e-6},
    "2027": {"input": 1.50e-6, "output": 7.50e-6, "embedding": 0.15e-6},
}


def cost(usage: dict, prices: dict) -> float:
    return (usage.get("input_tokens", 0) * prices["input"]
            + (usage.get("output_tokens", 0) + usage.get("thinking_tokens", 0)) * prices["output"]
            + usage.get("embedding_tokens", 0) * prices["embedding"])


def build_request(scenario: dict, data: dict) -> dict:
    defaults = data["defaults"]
    now = datetime.fromisoformat(scenario.get("now", defaults["now"]))
    busy = data["calendars"][scenario.get("calendar", defaults["calendar"])] + scenario.get("extra_busy", [])
    thread = scenario["thread"]
    return {
        "message_id": f"scenario-{scenario['name']}",
        "now": now.isoformat(),
        "user": scenario.get("user", defaults["user"]),
        "thread": thread,
        "target_index": len(thread) - 1,
        "classification": scenario["classification"],
        "busy": [{"start": s, "end": e} for s, e in busy],
        "busy_until": (now + timedelta(days=14)).isoformat(),
        "past_messages": scenario.get("past_messages", []),
    }


def interval(time_out: dict | None) -> slots.Interval | None:
    if not time_out:
        return None
    return slots.Interval(slots.to_utc(datetime.fromisoformat(time_out["start"])),
                          slots.to_utc(datetime.fromisoformat(time_out["end"])))


def recheck(request: dict, response: dict) -> list[str]:
    """Re-check the response's times and text against the scenario's calendar. Returns problems."""
    if response["status"] != "drafted":
        return []
    cal = slots.Calendar(
        busy=slots.merge_busy([(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
                               for b in request["busy"]]),
        rules=rules_for(request["user"]["email"]), now=datetime.fromisoformat(request["now"]),
        tz=ZoneInfo(request["user"]["timezone"]), busy_until=datetime.fromisoformat(request["busy_until"]))
    answer = checker.DraftAnswer(action=response["action"], draft_text=response["draft_text"],
                                 offered=[interval(t) for t in response["offered_times"]],
                                 accepted=interval(response["accepted_time"]),
                                 confirmed=interval(response["confirmed_time"]))
    thread_text = "\n".join(f"{m.get('from', '')}\n{m.get('to', '')}\n{m.get('subject', '')}\n{m.get('body', '')}"
                            for m in request["thread"])
    return [f"{c.name}: {c.detail}" for c in checker.run_checks(answer, cal, thread_text, request["user"]["email"])
            if not c.passed]


def expectations(expect: dict, response: dict, tz: ZoneInfo) -> list[tuple[str, bool]]:
    """(description, met) for each expectation."""
    results = [(f"status in {expect['status']}", response["status"] in expect["status"])]
    if response["status"] != "drafted":
        return results
    if "action" in expect:
        results.append((f"action in {expect['action']}", response["action"] in expect["action"]))
    if "offers" in expect:
        low, high = expect["offers"]
        count = len(response["offered_times"])
        results.append((f"offers {low}-{high} times", low <= count <= high))
        days = {t["start"][:10] for t in response["offered_times"]}
        results.append(("offers are on different days", len(days) == count))
    if "accepted_start" in expect:
        got = response["accepted_time"] and response["accepted_time"]["start"]
        same = bool(got) and datetime.fromisoformat(got) == datetime.fromisoformat(expect["accepted_start"])
        results.append((f"accepts {expect['accepted_start']}", same))
    if "confirmed_start" in expect:
        got = response["confirmed_time"] and response["confirmed_time"]["start"]
        same = bool(got) and datetime.fromisoformat(got) == datetime.fromisoformat(expect["confirmed_start"])
        results.append((f"confirms {expect['confirmed_start']}", same))
    if expect.get("offers_before_noon"):
        results.append(("offers only morning times (the sender's known preference)",
                        all(datetime.fromisoformat(t["end"]).astimezone(tz).hour < 12
                            or datetime.fromisoformat(t["end"]).astimezone(tz).strftime("%H:%M") == "12:00"
                            for t in response["offered_times"])))
    if "meeting_minutes" in expect:
        results.append((f"meeting length {expect['meeting_minutes']} min",
                        response["meeting_minutes"] == expect["meeting_minutes"]))
    for text in expect.get("must_include", []):
        results.append((f"draft mentions {text!r}", text in response["draft_text"]))
    for text in expect.get("must_not_include", []):
        results.append((f"draft never contains {text!r}", text.lower() not in response["draft_text"].lower()))
    return results


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=HERE, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run(only: str | None) -> list[dict]:
    data = json.loads(SCENARIOS.read_text())
    results = []
    for scenario in data["scenarios"]:
        if only and scenario["name"] != only:
            continue
        request = build_request(scenario, data)
        response = pipeline.run(DraftRequest(**request), main.deps)
        tz = ZoneInfo(request["user"]["timezone"])
        result = {"scenario": scenario, "request": request, "response": response,
                  "recheck": recheck(request, response), "expect": expectations(scenario["expect"], response, tz)}
        met = all(ok for _, ok in result["expect"])
        print(f"{scenario['name']:<34} {response['status']:<16} {str(response['action']):<16} "
              f"attempts={response['attempts']} {response['latency_ms']:>6} ms  "
              f"expectations={'met' if met else 'NOT met'}  recheck={'ok' if not result['recheck'] else 'FAILED'}")
        results.append(result)
    return results


def check_mark(ok: bool) -> str:
    return "✓" if ok else "✗"


def report(results: list[dict]) -> str:
    drafted = [r for r in results if r["response"]["status"] == "drafted"]
    called = [r for r in results if r["response"]["usage"]["gemini_calls"]]
    met = sum(all(ok for _, ok in r["expect"]) for r in results)
    rechecked_times = sum(len(r["response"]["offered_times"]) + bool(r["response"]["accepted_time"])
                          + bool(r["response"]["confirmed_time"]) for r in drafted)
    latencies = [r["response"]["latency_ms"] for r in called]
    costs = [cost(r["response"]["usage"], PRICES["now"]) for r in called]
    costs_2027 = [cost(r["response"]["usage"], PRICES["2027"]) for r in called]
    statuses = {}
    for r in results:
        statuses[r["response"]["status"]] = statuses.get(r["response"]["status"], 0) + 1

    lines = [
        "# Draft reply scenarios",
        "",
        f"Generated by [`src/drafter/run_scenarios.py`](../../../src/drafter/run_scenarios.py) on "
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC at commit `{git_commit()}`, with "
        f"`{main.MODEL}` (thinking budget {main.THINKING_BUDGET}) and `{main.EMBEDDING_MODEL}`, default rules "
        f"v{results[0]['response']['rules_version'] if results else '?'}. Every person, address and event is "
        "fictional ([`scenarios.json`](../../../src/drafter/scenarios/scenarios.json)), so drafts are shown in full.",
        "",
        "Unless a scenario says otherwise: it is Mon Nov 9, 2026, 10:00 AM in New York, the user is Sam Rivera "
        "(America/New_York), and the calendar is a typical student week (classes, lab, section) checked for 14 "
        "days, with the default rules (8 AM-8 PM every day, 24 h notice, 15 min buffer, 30 min meetings).",
        "",
        "## Summary",
        "",
        f"- **{len(results)} scenarios**: " + ", ".join(f"{n} {s}" for s, n in sorted(statuses.items())) + ".",
        f"- **Expectations met: {met} of {len(results)}.**",
        f"- **Times re-checked independently: {rechecked_times}** offered, accepted or confirmed times in "
        f"{len(drafted)} drafts, re-run through `checker.run_checks` against each scenario's calendar: "
        + ("**all passed**." if not any(r["recheck"] for r in results) else "**some FAILED** (see below)."),
        f"- **Gemini calls:** {sum(r['response']['usage']['gemini_calls'] for r in results)} for "
        f"{len(called)} scenarios that needed a draft ("
        f"{sum(r['response']['attempts'] == 2 for r in results)} needed the one retry). "
        "`no_reply_needed` and `no_free_time` make no model call.",
    ]
    if latencies:
        lines.append(f"- **Latency** (scenarios with a model call): median {statistics.median(latencies) / 1000:.1f} s, "
                     f"max {max(latencies) / 1000:.1f} s.")
        lines.append(f"- **Cost per draft** (Gemini + embeddings): mean ${statistics.mean(costs):.4f} "
                     f"(max ${max(costs):.4f}) at today's introductory price; ${statistics.mean(costs_2027):.4f} "
                     "from 2027-01-01. The scenarios pass their own classification; when the drafter has to call "
                     "the classifier, add about $0.003 ($0.006 from 2027).")
    lines += ["", "| Scenario | Label | Status | Action | Times | Checks | Tries | Latency | Cost | Expected |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        s, resp = r["scenario"], r["response"]
        times = "; ".join(t["label"] for t in resp["offered_times"])
        if resp["accepted_time"]:
            times = "accepts " + resp["accepted_time"]["label"]
        if resp["confirmed_time"]:
            times = "confirms " + resp["confirmed_time"]["label"]
        passed = sum(c["passed"] for c in resp["checks"])
        checks = f"{passed}/{len(resp['checks'])}" if resp["checks"] else "-"
        lines.append(f"| [{s['name']}](#{s['name']}) | {resp['label']} | {resp['status']} | "
                     f"{resp['action'] or '-'} | {times or '-'} | {checks} | {resp['attempts']} | "
                     f"{resp['latency_ms'] / 1000:.1f} s | ${cost(resp['usage'], PRICES['now']):.4f} | "
                     f"{check_mark(all(ok for _, ok in r['expect']))} |")

    for r in results:
        s, resp = r["scenario"], r["response"]
        lines += ["", f"## {s['name']}", "", s["about"], ""]
        lines.append(f"- **Status:** `{resp['status']}`" + (f" ({resp['error_type']}: {resp['error']})"
                                                           if resp["error"] else ""))
        lines.append(f"- **Label sent:** `{resp['label']}` (needs response: {str(resp['needs_response']).lower()}); meeting "
                     f"length {resp['meeting_minutes']} min" if resp["meeting_minutes"] else
                     f"- **Label sent:** `{resp['label']}` (needs response: {str(resp['needs_response']).lower()})")
        if resp["action"]:
            lines.append(f"- **Action:** `{resp['action']}`, {resp['attempts']} attempt(s), "
                         f"{resp['latency_ms'] / 1000:.1f} s")
        for t in resp["offered_times"]:
            lines.append(f"- **Offered:** {t['label']}")
        if resp["accepted_time"]:
            lines.append(f"- **Accepted:** {resp['accepted_time']['label']}")
        if resp["confirmed_time"]:
            lines.append(f"- **Confirmed:** {resp['confirmed_time']['label']}")
        usage = resp["usage"]
        lines.append(f"- **Tokens:** {usage['input_tokens']} in, {usage['output_tokens']} out, "
                     f"{usage['thinking_tokens']} thinking, {usage['embedding_tokens']} embedding; "
                     f"cost ${cost(usage, PRICES['now']):.4f}")
        if resp["context_used"]:
            lines.append("- **Past emails:** " + "; ".join(
                f"`{c['id']}` ({'cited: ' + c['why'] if c['cited'] else 'not cited, ' + c['why']})"
                for c in resp["context_used"]))
        for warning in resp["warnings"]:
            lines.append(f"- **Warning:** {warning}")
        lines.append("- **Expectations:** " + "; ".join(f"{check_mark(ok)} {what}" for what, ok in r["expect"]))
        lines.append("- **Independent re-check:** " + ("passed" if not r["recheck"] else "; ".join(r["recheck"]))
                     if resp["status"] == "drafted" else "- **Independent re-check:** nothing to check (no draft)")
        if resp["checks"]:
            lines += ["", "Checks:", ""]
            lines += [f"- {check_mark(c['passed'])} `{c['name']}`: {c['detail']}" for c in resp["checks"]]
        if resp["draft_text"]:
            lines += ["", "Draft:", "", "```text", resp["draft_text"], "```"]
    return "\n".join(lines) + "\n"


def main_cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="run one scenario by name")
    parser.add_argument("--no-write", action="store_true", help="don't write the report")
    args = parser.parse_args()
    logs.setup(logging.WARNING)  # keep the console to one line per scenario
    results = run(args.only)
    if not args.no_write and not args.only:
        REPORT.write_text(report(results), encoding="utf-8")
        print(f"wrote {REPORT.relative_to(HERE.parent.parent)}")
    if any(r["recheck"] for r in results):
        print("FAILED: a returned time or text failed the independent re-check", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
