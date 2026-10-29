"""Score predictions against the correct answers and write report.md.

Every function takes a DataFrame with one row per message: message_id,
user_id, subject, true_label, pred_label, true_needs_response,
pred_needs_response, reason, error, latency_s and token counts. Rows whose
call failed (`error` set) are counted as failures and left out of the scores.
"""

import pandas as pd
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from prompt import LABELS

SCHEDULING_LABELS = [label for label in LABELS if label != "none"]

# Per-user breakdown: user_04 (studying abroad, London time zone) is kept apart.
USER_GROUPS = {"user_01–03": ["user_01", "user_02", "user_03"], "user_04": ["user_04"]}

# Vertex AI prices, US$ per 1M tokens (input, output; thinking tokens bill as output).
# Estimates only, as of 2026-10-29 (gemini-3.8-flash from third-party price lists,
# reported as introductory). Check https://cloud.google.com/vertex-ai/generative-ai/pricing.
PRICES = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3-flash-preview": (0.50, 3.00),
}


def scored(df: pd.DataFrame) -> pd.DataFrame:
    """Rows with a valid prediction."""
    return df[df["error"].isna()]


def label_accuracy(df: pd.DataFrame) -> float:
    ok = scored(df)
    return float((ok["true_label"] == ok["pred_label"]).mean()) if len(ok) else float("nan")


def per_label_table(df: pd.DataFrame) -> pd.DataFrame:
    ok = scored(df)
    p, r, f1, support = precision_recall_fscore_support(
        ok["true_label"], ok["pred_label"], labels=LABELS, zero_division=0
    )
    return pd.DataFrame({"precision": p, "recall": r, "f1": f1, "support": support}, index=LABELS)


def confusion(df: pd.DataFrame) -> pd.DataFrame:
    """Rows: true label, columns: predicted label."""
    ok = scored(df)
    return pd.DataFrame(confusion_matrix(ok["true_label"], ok["pred_label"], labels=LABELS), index=LABELS, columns=LABELS)


def scheduling_recall(df: pd.DataFrame) -> dict:
    """How many scheduling emails (any of the five scheduling labels) were not predicted `none`.

    `missed` (scheduling email predicted `none`) is the worst error: Fixture would
    ignore the email. `false_alarms` is the reverse: a `none` email treated as scheduling.
    """
    ok = scored(df)
    sched = ok[ok["true_label"].isin(SCHEDULING_LABELS)]
    not_sched = ok[ok["true_label"] == "none"]
    missed = int((sched["pred_label"] == "none").sum())
    false_alarms = int((not_sched["pred_label"] != "none").sum())
    return {
        "n": len(sched),
        "recall": 1 - missed / len(sched) if len(sched) else float("nan"),
        "missed": missed,
        "n_none": len(not_sched),
        "false_alarms": false_alarms,
    }


def needs_response_metrics(df: pd.DataFrame) -> dict:
    ok = scored(df)
    true = ok["true_needs_response"].astype(bool)
    pred = ok["pred_needs_response"].astype(bool)
    tp = int((true & pred).sum())
    return {
        "accuracy": float((true == pred).mean()) if len(ok) else float("nan"),
        "precision": tp / int(pred.sum()) if pred.sum() else float("nan"),
        "recall": tp / int(true.sum()) if true.sum() else float("nan"),
        "n_true": int(true.sum()),
        "missed": int((true & ~pred).sum()),  # user owed a reply, Gemini said no
        "extra": int((~true & pred).sum()),
    }


def hard_negative_accuracy(df: pd.DataFrame) -> dict | None:
    """Label accuracy on messages the annotations mark as hard negatives; None if none are marked."""
    if "hard_negative" not in df or not df["hard_negative"].fillna(False).astype(bool).any():
        return None
    ok = scored(df)
    hard = ok[ok["hard_negative"].fillna(False).astype(bool)]
    return {"n": len(hard), "accuracy": float((hard["true_label"] == hard["pred_label"]).mean())}


def by_user(df: pd.DataFrame) -> pd.DataFrame:
    groups = {u: [u] for u in sorted(df["user_id"].unique())} | USER_GROUPS | {"all": list(df["user_id"].unique())}
    rows = {}
    for name, users in groups.items():
        part = df[df["user_id"].isin(users)]
        if part.empty:
            continue
        sched = scheduling_recall(part)
        rows[name] = {
            "messages": len(part),
            "failures": int(part["error"].notna().sum()),
            "label_acc": label_accuracy(part),
            "sched_recall": sched["recall"],
            "sched_as_none": sched["missed"],
            "nr_acc": needs_response_metrics(part)["accuracy"],
        }
    return pd.DataFrame.from_dict(rows, orient="index")


def usage(df: pd.DataFrame, prices: tuple[float, float] | None) -> dict:
    """Token totals, estimated cost (list price, no caching discount) and latency."""
    ok = scored(df)
    totals = {k: int(df[k].fillna(0).sum()) if k in df else 0 for k in ["input_tokens", "cached_input_tokens", "output_tokens", "thinking_tokens"]}
    cost = None
    if prices:
        price_in, price_out = prices
        cost = (totals["input_tokens"] * price_in + (totals["output_tokens"] + totals["thinking_tokens"]) * price_out) / 1e6
    latency = ok["latency_s"] if "latency_s" in ok else pd.Series(dtype=float)
    return totals | {
        "cost_usd": cost,
        "latency_median_s": float(latency.median()) if len(latency) else float("nan"),
        "latency_p95_s": float(latency.quantile(0.95)) if len(latency) else float("nan"),
    }


def mistake_kind(row) -> tuple[int, str] | None:
    """(severity tier, kind) for a wrong prediction, or None if it's right. Lower tier = worse."""
    true, pred = row["true_label"], row["pred_label"]
    if true != pred:
        if true in SCHEDULING_LABELS and pred == "none":
            return 0, f"{true} → none (scheduling missed)"
        if true == "none":
            return 1, f"none → {pred} (false alarm)"
        return 2, f"{true} → {pred}"
    if bool(row["true_needs_response"]) != bool(row["pred_needs_response"]):
        direction = "reply missed" if row["true_needs_response"] else "extra reply"
        return 3, f"{true}: needs_response {direction}"
    return None


def informative_mistakes(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Up to `n` mistakes, spread over the kinds of error, worst kinds first.

    Groups the mistakes by kind (e.g. "reschedule → proposed_times"), orders
    the groups by severity tier then size, and takes one from each group in
    turn, so one common confusion can't fill the whole list.
    """
    ok = scored(df).copy()
    kinds = ok.apply(mistake_kind, axis=1)
    ok["tier"] = [k[0] if k else None for k in kinds]
    ok["kind"] = [k[1] if k else None for k in kinds]
    wrong = ok[ok["kind"].notna()]
    groups = sorted(
        (group for _, group in wrong.groupby("kind")),
        key=lambda g: (g["tier"].iloc[0], -len(g)),
    )
    picked, round_ = [], 0
    while len(picked) < n and any(round_ < len(g) for g in groups):
        for g in groups:
            if round_ < len(g) and len(picked) < n:
                picked.append(g.iloc[round_])
        round_ += 1
    result = pd.DataFrame(picked)
    return result.sort_values(["tier", "kind"], kind="stable") if len(result) else result


def counts_of_mistake_kinds(df: pd.DataFrame) -> pd.Series:
    kinds = scored(df).apply(mistake_kind, axis=1).dropna()
    return pd.Series([k[1] for k in kinds], dtype=object).value_counts()


# ---- report.md ----


def fmt(x, digits: int = 3) -> str:
    if isinstance(x, float):
        return "n/a" if pd.isna(x) else f"{x:.{digits}f}"
    return str(x)


def md_table(df: pd.DataFrame, index_name: str = "") -> str:
    header = [index_name, *map(str, df.columns)]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for index, row in df.astype(object).iterrows():  # object: counts stay ints, not 3.000
        lines.append("| " + " | ".join([str(index), *(fmt(v) for v in row)]) + " |")
    return "\n".join(lines)


def cell(text: str) -> str:
    """Make text safe for one markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_report(df: pd.DataFrame, info: dict) -> str:
    sched = scheduling_recall(df)
    nr = needs_response_metrics(df)
    use = usage(df, info.get("prices"))
    failures = df[df["error"].notna()]
    hard = hard_negative_accuracy(df)

    out = [f"# Gemini baseline: {info['model']} on the training data", ""]
    out += [
        "## Run",
        "",
        f"- Model: `{info['model']}` (served as {', '.join(f'`{v}`' for v in info['model_versions']) or 'n/a'}), "
        f"Vertex AI `{info['project']}` / `{info['location']}`, temperature 0, structured JSON output",
        f"- Labeling rules: v{info['rules_version']} (`docs/data/labeling_rules.md`, without the "
        f"\"Not adopted\" and \"Change log\" sections); annotations follow v{info['annotation_rules_version']}",
        f"- Git commit: `{info['git_commit']}`",
        f"- Date: {info['date']}",
        f"- Messages: {len(df)}{' (--limit ' + str(info['limit']) + ')' if info.get('limit') else ''}, "
        f"users {', '.join(sorted(df['user_id'].unique()))}",
        f"- Failures: {len(failures)} (left out of every score below)",
        "",
    ]
    if len(failures):
        out += ["| message_id | error |", "|---|---|"]
        out += [f"| {r.message_id} | {cell(r.error)} |" for r in failures.itertuples()]
        out.append("")

    out += [
        "## Labels",
        "",
        f"**Accuracy: {fmt(label_accuracy(df))}** on {len(scored(df))} messages.",
        "",
        md_table(per_label_table(df), "label"),
        "",
        "### Confusion matrix (rows: true label, columns: predicted)",
        "",
        md_table(confusion(df), "true \\ pred"),
        "",
        "### Scheduling vs `none`",
        "",
        f"- **Recall on the five scheduling labels combined: {fmt(sched['recall'])}** "
        f"({sched['missed']} of {sched['n']} scheduling emails predicted `none`, the worst error)",
        f"- False alarms: {sched['false_alarms']} of {sched['n_none']} `none` emails predicted as a scheduling label",
        "- Hard negatives: "
        + (
            f"accuracy {fmt(hard['accuracy'])} on {hard['n']} marked messages"
            if hard
            else "not scored. `data/source/annotations.jsonl` doesn't mark hard negatives "
            "(only the generation outlines in `docs/data/generation/` mention some in prose)."
        ),
        "",
        "## needs_response",
        "",
        f"- Accuracy {fmt(nr['accuracy'])}, precision {fmt(nr['precision'])}, recall {fmt(nr['recall'])} "
        f"({nr['n_true']} messages need a response)",
        f"- Replies missed (true, predicted false): {nr['missed']}; extra (false, predicted true): {nr['extra']}",
        "",
        "## By user",
        "",
        md_table(by_user(df), "users"),
        "",
        "## Cost and latency",
        "",
        f"- Tokens: {use['input_tokens']:,} input ({use['cached_input_tokens']:,} of them served from Vertex's "
        f"implicit cache), {use['output_tokens']:,} output, {use['thinking_tokens']:,} thinking",
        "- Estimated cost: "
        + (
            f"${use['cost_usd']:.2f} at ${info['prices'][0]}/1M input and ${info['prices'][1]}/1M output+thinking "
            "(list price, no caching discount)"
            if use["cost_usd"] is not None
            else "n/a (no price known for this model; pass --price-input and --price-output)"
        ),
        f"- Latency per call: median {fmt(use['latency_median_s'], 2)} s, p95 {fmt(use['latency_p95_s'], 2)} s "
        f"(concurrency {info['concurrency']})",
        "",
        "## Mistakes",
        "",
        "All mistakes by kind (label mistakes first; a needs_response mistake is only counted when the label is right):",
        "",
    ]
    kinds = counts_of_mistake_kinds(df)
    out += [f"- {kind}: {count}" for kind, count in kinds.items()] or ["- none"]
    out += [
        "",
        "### The 20 most informative",
        "",
        "Spread over the kinds of error, worst first: scheduling missed, false alarms, wrong "
        "scheduling label, then needs_response.",
        "",
        "| message_id | user | subject | true | predicted | needs_response true → pred | Gemini's reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in informative_mistakes(df).itertuples():
        out.append(
            f"| {r.message_id} | {r.user_id} | {cell(r.subject)} | {r.true_label} | {r.pred_label} | "
            f"{r.true_needs_response} → {r.pred_needs_response} | {cell(r.reason)} |"
        )
    return "\n".join(out) + "\n"
