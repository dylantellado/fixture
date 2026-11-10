"""Score predictions. needs_response is the target; label accuracy is reported alongside.

The number that matters most for Fixture is missed responses (true needs_response
predicted false): an email the user should answer that Fixture would sit on.
"""

from collections import Counter, defaultdict


def binary(pairs: list[tuple[bool, bool]]) -> dict:
    """Accuracy, precision, recall and F1 for (true, predicted) pairs, positive = needs a response."""
    tp = sum(t and p for t, p in pairs)
    fp = sum((not t) and p for t, p in pairs)
    fn = sum(t and (not p) for t, p in pairs)
    tn = sum((not t) and (not p) for t, p in pairs)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"n": len(pairs), "accuracy": (tp + tn) / len(pairs) if pairs else 0.0, "precision": precision,
            "recall": recall, "f1": f1, "missed": fn, "false_alarms": fp, "tp": tp, "tn": tn}


def score(predictions: list[dict]) -> dict:
    """Headline metrics plus breakdowns by source set (v1 vs generated) and by act."""
    ok = [p for p in predictions if p.get("error") is None]
    pairs = [(p["true_needs_response"], p["needs_response"]) for p in ok]
    result = {f"needs_response/{k}": v for k, v in binary(pairs).items()}
    result["label/accuracy"] = sum(p["label"] == p["true_label"] for p in ok) / len(ok) if ok else 0.0
    result["failures"] = len(predictions) - len(ok)
    groups = defaultdict(list)
    for p in ok:
        groups[f"by_source/{p['source_set']}"].append(p)
        if p.get("act"):
            groups[f"by_act/{p['act']}"].append(p)
    for name, items in groups.items():
        r = binary([(p["true_needs_response"], p["needs_response"]) for p in items])
        result[f"{name}/needs_response_accuracy"] = r["accuracy"]
        result[f"{name}/n"] = r["n"]
    return result


def confusion(predictions: list[dict]) -> Counter:
    return Counter((p["true_label"], p["label"]) for p in predictions if p.get("error") is None)
