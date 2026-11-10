"""The steps of one draft, as a plain function so anything can call it.

run(request, deps) is what POST /draft does. A Gmail watcher can later call the
same function (or the endpoint) for each new email that needs a reply.

  1. Classification: use the one sent, or ask the classifier. No reply needed
     (or the user sent the email) -> status no_reply_needed, no Gemini call.
  2. Rules and calendar (rules.py, slots.py): free slots and windows for the
     meeting length. Nothing free for an email that needs times offered ->
     status no_free_time, no Gemini call.
  3. Context (context.py): the 5 most relevant past emails with the sender.
  4. Draft (draft.py): one Gemini call.
  5. Check (checker.py). If any check fails, draft once more with the failures
     explained, and check again. Still failing -> status error, with the
     checks and no draft text. An unchecked draft is never returned.

Every request logs one JSON line (logs.py): counts, statuses, check names,
tokens and timing; never email text, names, addresses or the draft.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import checker
import context as context_module
import draft
import slots
from classifier_client import ClassifierError
from gemini import GeminiError
from rules import NoStoredRules, RulesStore, describe, rules_for
from schemas import DraftRequest

log = logging.getLogger("drafter")

TEMPERATURE = 0.2  # low: replies should be predictable
REGENERATE_TEMPERATURE = 0.7  # "Regenerate" asks for a different wording
# Labels whose reply offers times (or accepts one of the sender's).
SLOT_LABELS = {"new_request", "reschedule", "proposed_times", "assistant_handoff"}


@dataclass
class Deps:
    """What the pipeline calls out to. Tests pass fakes; main.py passes the real ones."""

    gemini: object  # .generate_json(system, user, schema, temperature) -> (dict, usage)
    embedder: object  # .embed(texts, task_type) -> (vectors, tokens)
    classifier: object | None  # .classify(thread, target_index, message_id) -> dict
    model: str
    embedding_model: str
    rules_store: RulesStore = NoStoredRules()


def _time_out(interval: slots.Interval | None, tz: ZoneInfo) -> dict | None:
    if interval is None:
        return None
    return {"start": slots.iso_local(interval.start, tz), "end": slots.iso_local(interval.end, tz),
            "label": slots.format_interval(interval, tz)}


def run(request: DraftRequest, deps: Deps) -> dict:
    """Draft a reply to request.thread[request.target_index]. Returns a DraftResponse dict.

    Raises ValueError for invalid rule overrides (main.py turns that into a 422).
    """
    started = time.perf_counter()
    rules = rules_for(request.user.email, request.rules, deps.rules_store)
    tz = ZoneInfo(request.user.timezone)
    now = request.now or datetime.now(timezone.utc)
    thread = [m.as_dict() for m in request.thread[:request.target_index + 1]]
    target_index = request.target_index
    target = thread[target_index]

    response = {"status": "error", "draft_text": "", "action": None, "offered_times": [], "accepted_time": None,
                "confirmed_time": None, "checks": [], "context_used": [], "warnings": [], "error": None,
                "error_type": None, "label": None, "needs_response": None, "meeting_minutes": None,
                "model": deps.model, "rules_version": rules.version, "attempts": 0, "latency_ms": 0,
                "usage": {"gemini_calls": 0, "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0,
                          "embedding_tokens": 0, "classifier_called": False}}
    fields = {"event": "draft", "message_id": request.message_id or None, "thread_length": len(thread),
              "busy_count": len(request.busy), "past_messages": len(request.past_messages), "model": deps.model,
              "embedding_model": deps.embedding_model, "rules_version": rules.version,
              "rules_custom": "+" in rules.version}

    def finish(status: str, error_type: str | None = None, error: str | None = None) -> dict:
        response.update(status=status, error_type=error_type, error=error,
                        latency_ms=round((time.perf_counter() - started) * 1000))
        usage = response["usage"]
        checks = response["checks"]
        log_fields = {**fields, "status": status, "error_type": error_type, "label": response["label"],
                      "needs_response": response["needs_response"], "action": response["action"],
                      "meeting_minutes": response["meeting_minutes"], "attempts": response["attempts"],
                      "offered_count": len(response["offered_times"]),
                      "accepted": response["accepted_time"] is not None,
                      "confirmed": response["confirmed_time"] is not None,
                      "checks_passed": sum(c["passed"] for c in checks),
                      "checks_failed": sum(not c["passed"] for c in checks),
                      "failed_checks": [c["name"] for c in checks if not c["passed"]] or None,
                      "context_used": sum(c["cited"] for c in response["context_used"]),
                      "warnings_count": len(response["warnings"]), "latency_ms": response["latency_ms"],
                      "gemini_calls": usage["gemini_calls"], "input_tokens": usage["input_tokens"],
                      "output_tokens": usage["output_tokens"], "thinking_tokens": usage["thinking_tokens"],
                      "embedding_tokens": usage["embedding_tokens"]}
        level = logging.ERROR if status == "error" else logging.INFO
        log.log(level, "draft: status=%s label=%s attempts=%d latency_ms=%d", status, response["label"],
                response["attempts"], response["latency_ms"], extra={"fields": log_fields})
        return response

    # 1. Classification.
    if request.classification is not None:
        classification = request.classification.model_dump()
        fields["classification_source"] = "request"
    else:
        fields["classification_source"] = "classifier"
        if deps.classifier is None:
            return finish("error", "classifier_unavailable", "No classification was sent and no classifier is set.")
        call_started = time.perf_counter()
        try:
            classification = deps.classifier.classify(thread, target_index, request.message_id)
        except ClassifierError as error:
            return finish("error", "classifier_unavailable", f"Couldn't classify the email: {error}.")
        finally:
            fields["classify_ms"] = round((time.perf_counter() - call_started) * 1000)
        response["usage"]["classifier_called"] = True
    label = classification["label"]
    needs_response = bool(classification["needs_response"]) and not target["from_user"]
    response.update(label=label, needs_response=needs_response)
    if not needs_response:
        return finish("no_reply_needed")

    # 2. Rules and calendar.
    cal = slots.Calendar(busy=slots.merge_busy([(b.start, b.end) for b in request.busy]), rules=rules, now=now,
                         tz=tz, busy_until=request.busy_until)
    bodies = [m["body"] for m in reversed(thread)]  # most recent first
    minutes, minutes_source = slots.meeting_minutes(bodies, rules.default_meeting_minutes)
    all_slots = slots.free_slots(cal, minutes)
    windows = slots.free_windows(cal, minutes)
    candidates = slots.pick_candidates(all_slots, tz)
    response["meeting_minutes"] = minutes
    fields.update(meeting_minutes_source=minutes_source, allowed_slots=len(candidates), free_windows=len(windows))
    # The caller fetched busy times up to busy_until; slots end there (Calendar.horizon_end).
    # Warn if that cuts the horizon short by more than an hour (a few seconds is just clock skew).
    if request.busy_until and request.busy_until < now + timedelta(days=rules.horizon_days, hours=-1):
        response["warnings"].append(
            f"Your calendar was only checked until {slots.clock(request.busy_until.astimezone(tz))} on "
            f"{request.busy_until.astimezone(tz):%a, %b} {request.busy_until.astimezone(tz).day}; "
            "no later times are offered.")
    if label in SLOT_LABELS and not candidates and (label != "proposed_times" or not windows):
        response["warnings"].append(
            f"No free {minutes}-minute time in the next {rules.horizon_days} days fits your rules "
            f"({describe(rules)}).")
        return finish("no_free_time")

    # 3. Context.
    context_started = time.perf_counter()
    ctx = context_module.get_relevant_context(
        request.user.model_dump(), thread, target_index, [m.as_dict() | {"thread_id": m.thread_id}
                                                          for m in request.past_messages], deps.embedder)
    fields.update(context_ms=round((time.perf_counter() - context_started) * 1000), context_method=ctx.method)
    response["usage"]["embedding_tokens"] = ctx.embedding_tokens
    response["warnings"] += ctx.warnings

    # 4 and 5. Draft, check, and retry once.
    system, user_prompt = draft.build_prompt(
        thread=thread, target_index=target_index, user=request.user.model_dump(), label=label,
        needs_response=needs_response, reason=classification.get("reason", ""), cal=cal, rules=rules,
        minutes=minutes, minutes_source=minutes_source, candidates=candidates, windows=windows, context=ctx)
    temperature = REGENERATE_TEMPERATURE if request.regenerate else TEMPERATURE
    fields["temperature"] = temperature
    thread_text = "\n".join(f"{m['from']}\n{m['to']}\n{m['subject']}\n{m['body']}" for m in thread)
    context_ids = {str(item.message.get("id")) for item in ctx.items}

    prompt, answer, checks = user_prompt, None, []
    gemini_started = time.perf_counter()
    for attempt in (1, 2):
        try:
            raw, usage = draft.ask_model(deps.gemini, system, prompt, temperature)
        except GeminiError as error:
            fields.update(gemini_code=error.code, gemini_ms=round((time.perf_counter() - gemini_started) * 1000))
            response["checks"] = [c.as_dict() for c in checks]
            return finish("error", "gemini_unavailable", f"Gemini couldn't write a draft ({error.kind}).")
        response["attempts"] = attempt
        totals = response["usage"]
        totals["gemini_calls"] += 1
        for key in ("input_tokens", "output_tokens", "thinking_tokens"):
            totals[key] += usage.get(key, 0)
        answer = draft.parse_answer(raw, candidates, context_ids)
        checks = checker.run_checks(answer, cal, thread_text, request.user.email)
        failures = checker.failed(checks)
        if not failures:
            break
        prompt = draft.retry_prompt(user_prompt, answer.draft_text, [c.as_dict() for c in failures])
    fields["gemini_ms"] = round((time.perf_counter() - gemini_started) * 1000)

    response["checks"] = [c.as_dict() for c in checks]
    response["action"] = answer.action
    cited = {c["id"]: c["why"] for c in answer.context_used}
    response["context_used"] = [
        {"id": str(item.message.get("id")), "score": item.score, "cited": str(item.message.get("id")) in cited,
         "why": cited.get(str(item.message.get("id"))) or (
             f"Ranked #{item.rank} of {ctx.candidates} past emails by similarity ({item.score:.2f})"
             if item.score is not None else f"One of the {len(ctx.items)} most recent past emails")}
        for item in ctx.items]
    if checker.failed(checks):
        # Never return a draft that failed a check, not even as a preview.
        return finish("error", "checks_failed", "Fixture couldn't write a draft that passes every check.")

    response["draft_text"] = answer.draft_text
    response["offered_times"] = [_time_out(t, tz) for t in answer.offered]
    response["accepted_time"] = _time_out(answer.accepted, tz)
    response["confirmed_time"] = _time_out(answer.confirmed, tz)
    response["warnings"] += checker.warnings_for(answer, candidates, cal)
    return finish("drafted")
