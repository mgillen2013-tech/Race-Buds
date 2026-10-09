"""Live race stats: formatting, projected finish, and segment results computed from mile splits.

Plain functions with no Flask, so they're easy to test (tests/test_stats.py).
The raw input is a dict like:
    {"updatedAt": "2026-11-01T14:03:22Z", "distanceMi": 14.2, "elapsedSec": 5855,
     "paceSecPerMi": 412, "heartRate": 158, "splits": [{"mile": 1, "secs": 418, "hr": 146}, ...]}
where splits are completed miles only. None means no data yet (the run hasn't started).
"""
from datetime import datetime, timedelta, timezone

RACE_MILES = 26.2
STALE_AFTER_SEC = 90


# ---- Formatting ----
def fmt_time(secs) -> str:
    """m:ss under an hour, h:mm:ss from an hour up."""
    secs = int(round(secs))
    h, rest = divmod(secs, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_miles(miles) -> str:
    """14.2 -> '14.2', 13.0 -> '13'."""
    return f"{round(miles, 1):g}"


def ago_text(secs) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs} sec ago"
    if secs < 3600:
        return f"{secs // 60} min ago"
    return f"{secs // 3600} hr ago"


# ---- Computed numbers ----
def projected_finish(distance, elapsed, splits, finished=False):
    """elapsed + remaining miles * recent pace (mean of the last 3 miles, or overall pace before mile 3).
    None before the first mile is done."""
    if finished:
        return elapsed
    if not splits or distance <= 0:
        return None
    if len(splits) >= 3:
        recent = sum(s["secs"] for s in splits[-3:]) / 3
    else:
        recent = elapsed / distance
    return elapsed + max(0.0, RACE_MILES - distance) * recent


def segments(splits, distance, elapsed, heart_rate=None, size=4, in_progress=True, keep=3):
    """Group splits into blocks of `size` miles. The unfinished block also counts the partial mile
    (distance and time past the last split) and is labeled like 'Miles 13–14.2'.
    Pace is total time / total distance. Returns the last `keep` blocks."""
    n = len(splits)
    blocks = [splits[i:i + size] for i in range(0, n, size)]
    partial_mi = distance - n
    partial_sec = elapsed - sum(s["secs"] for s in splits)
    has_partial = partial_mi >= 0.05 and partial_sec > 0
    if has_partial and n % size == 0:
        blocks.append([])  # a new block has just begun

    out = []
    for i, chunk in enumerate(blocks):
        first = i * size + 1
        last_block = i == len(blocks) - 1
        secs = sum(s["secs"] for s in chunk)
        miles = float(len(chunk))
        end = fmt_miles(first + len(chunk) - 1) if chunk else None
        if last_block and has_partial:
            secs += partial_sec
            miles += partial_mi
            end = fmt_miles(distance)
        if miles <= 0:
            continue
        hrs = [s["hr"] for s in chunk if s.get("hr")]
        avg_hr = round(sum(hrs) / len(hrs)) if hrs else heart_rate
        unfinished = has_partial or len(chunk) < size
        # Only the partial mile so far (e.g. 4.5 mi into block 5-8): just "Mile 5"
        label = f"Mile {first}" if not chunk or end == str(first) else f"Miles {first}–{end}"
        pace = secs / miles
        out.append({
            "label": label,
            "paceSecPerMi": round(pace),
            "avgHr": avg_hr,
            "current": bool(last_block and unfinished and in_progress),
            "paceText": fmt_time(pace),
        })
    return out[-keep:]


def build(raw, segment_miles=4, now=None):
    """Turn raw data into the /api/stats payload, including ready-to-show text."""
    now = now or datetime.now(timezone.utc)
    if not raw or not raw.get("updatedAt"):
        return {
            "status": "waiting", "updatedAt": None, "distanceMi": None, "elapsedSec": None,
            "paceSecPerMi": None, "heartRate": None, "splits": [],
            "projectedFinishSec": None, "segments": [], "progress": 0,
            "text": {"where": f"{fmt_miles(RACE_MILES)} miles"},
        }

    updated = datetime.fromisoformat(raw["updatedAt"].replace("Z", "+00:00"))
    age = max(0, (now - updated).total_seconds())
    distance = float(raw.get("distanceMi") or 0)
    elapsed = float(raw.get("elapsedSec") or 0)
    splits = raw.get("splits") or []
    pace = raw.get("paceSecPerMi")
    hr = raw.get("heartRate")

    finished = distance >= RACE_MILES or bool(raw.get("ended"))  # ended: the watch was stopped
    status = "finished" if finished else ("stale" if age > STALE_AFTER_SEC else "live")
    projected = projected_finish(distance, elapsed, splits, finished)
    segs = segments(splits, distance, elapsed, hr, segment_miles, in_progress=not finished)

    return {
        "status": status,
        "updatedAt": raw["updatedAt"],
        "distanceMi": distance,
        "elapsedSec": int(elapsed),
        "paceSecPerMi": pace,
        "heartRate": hr,
        "splits": splits,
        "projectedFinishSec": None if projected is None else int(round(projected)),
        "segments": segs,
        "progress": min(1.0, distance / RACE_MILES),
        "text": {
            "where": f"{fmt_miles(distance)} miles" if finished else f"Mile {fmt_miles(distance)} of {fmt_miles(RACE_MILES)}",
            "distance": fmt_miles(distance),
            "elapsed": fmt_time(elapsed),
            "pace": fmt_time(pace) if pace else None,
            "heartRate": str(hr) if hr else None,
            "projected": None if projected is None else fmt_time(projected),
            "updatedAgo": ago_text(age),
        },
    }


# ---- Demo data (DEMO_STATS=1): sample numbers so the page can be checked without a run ----
def demo_raw(variant="live", now=None):
    now = now or datetime.now(timezone.utc)
    if variant == "waiting":
        return None
    hrs = [144, 146, 147, 149, 151, 152, 152, 153, 154, 155, 156, 156, 157, 158]
    secs = [418, 416, 415, 414, 411, 411, 410, 412, 412, 412, 413, 411, 409, 408]
    if variant == "finished":
        secs = secs + [410] * 12
        hrs = hrs + [160] * 12
    splits = [{"mile": i + 1, "secs": s, "hr": h} for i, (s, h) in enumerate(zip(secs, hrs))]
    distance = len(splits) + 0.2
    elapsed = sum(secs) + 82  # the 0.2 past the last split, at about 6:50 /mi
    updated = now - timedelta(seconds=150 if variant == "stale" else 4)
    return {
        "updatedAt": updated.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "distanceMi": distance,
        "elapsedSec": elapsed,
        "paceSecPerMi": 412,
        "heartRate": 158,
        "splits": splits,
    }
