from datetime import datetime, timedelta, timezone

import pytest

import stats

NOW = datetime(2026, 11, 1, 14, 0, 0, tzinfo=timezone.utc)


def splits_of(*secs, hr=150):
    return [{"mile": i + 1, "secs": s, "hr": hr} for i, s in enumerate(secs)]


def raw(splits, distance, elapsed, age=5, hr=150):
    return {
        "updatedAt": (NOW - timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "distanceMi": distance, "elapsedSec": elapsed, "paceSecPerMi": 420, "heartRate": hr,
        "splits": splits,
    }


# ---- formatting ----
@pytest.mark.parametrize("secs,text", [
    (0, "0:00"), (59, "0:59"), (412, "6:52"), (3599, "59:59"), (3600, "1:00:00"), (5855, "1:37:35"),
    (10752, "2:59:12"),
])
def test_fmt_time(secs, text):
    assert stats.fmt_time(secs) == text


def test_parse_goal():
    assert stats.parse_goal("3:00:00") == 10800
    assert stats.parse_goal("3:30") == 12600
    with pytest.raises(ValueError):
        stats.parse_goal("180")


def test_fmt_miles():
    assert stats.fmt_miles(14.2) == "14.2"
    assert stats.fmt_miles(13.0) == "13"
    assert stats.fmt_miles(26.2) == "26.2"


# ---- projected finish ----
def test_projected_equal_splits():
    # 10 miles at exactly 7:00, on pace at 10.0 -> 26.2 * 420
    s = splits_of(*[420] * 10)
    assert stats.projected_finish(10.0, 4200, s) == pytest.approx(26.2 * 420)


def test_projected_uses_last_three_miles():
    # older miles slow, last three at 6:00 -> remaining 16.2 mi at 360
    s = splits_of(500, 500, 360, 360, 360)
    elapsed = sum(x["secs"] for x in s)
    assert stats.projected_finish(5.0, elapsed, s) == pytest.approx(elapsed + 21.2 * 360)


def test_projected_before_mile_three_uses_overall_pace():
    s = splits_of(400, 440)
    # 2.5 mi in 1050 s -> 420 /mi overall
    assert stats.projected_finish(2.5, 1050, s) == pytest.approx(1050 + 23.7 * 420)


def test_projected_none_before_mile_one():
    assert stats.projected_finish(0.6, 250, []) is None


def test_gap_sign():
    assert stats.gap_text(10752, 10800) == "48 sec under a 3:00:00 goal"
    assert stats.gap_text(10872, 10800) == "1:12 over a 3:00:00 goal"
    assert stats.gap_text(10800, 10800) == "Right on a 3:00:00 goal"


# ---- segments ----
def test_segments_equal_splits():
    s = splits_of(*[420] * 8)
    segs = stats.segments(s, 8.0, 3360, size=4)
    assert [g["label"] for g in segs] == ["Miles 1–4", "Miles 5–8"]
    assert all(g["paceSecPerMi"] == 420 and not g["current"] for g in segs)


def test_segments_partial_final_block():
    # 14 miles done + 0.2 mi in 80 s. Block 13-16 holds miles 13, 14 and the partial.
    s = splits_of(*[420] * 12, 400, 410)
    elapsed = sum(x["secs"] for x in s) + 80
    segs = stats.segments(s, 14.2, elapsed, size=4)
    assert [g["label"] for g in segs] == ["Miles 5–8", "Miles 9–12", "Miles 13–14.2"]
    last = segs[-1]
    assert last["current"] is True
    # total time / total distance, not an average of paces
    assert last["paceSecPerMi"] == round((400 + 410 + 80) / 2.2)


def test_segments_new_block_only_partial():
    s = splits_of(*[420] * 4)
    segs = stats.segments(s, 4.5, 4 * 420 + 200, heart_rate=161, size=4)
    assert segs[-1]["label"] == "Mile 5"
    assert segs[-1]["current"] and segs[-1]["avgHr"] == 161
    assert segs[-1]["paceSecPerMi"] == 400


def test_segments_fewer_than_three_miles():
    s = splits_of(430, 410, hr=148)
    segs = stats.segments(s, 2.4, 840 + 170, size=4)
    assert len(segs) == 1
    assert segs[0]["label"] == "Miles 1–2.4"
    assert segs[0]["current"] and segs[0]["avgHr"] == 148


def test_segments_average_hr_is_mean_of_splits():
    s = [{"mile": 1, "secs": 420, "hr": 140}, {"mile": 2, "secs": 420, "hr": 150},
         {"mile": 3, "secs": 420, "hr": 160}, {"mile": 4, "secs": 420, "hr": 151}]
    assert stats.segments(s, 4.0, 1680, size=4)[0]["avgHr"] == 150


# ---- full payload ----
def test_build_waiting():
    p = stats.build(None, 10800, now=NOW)
    assert p["status"] == "waiting" and p["projectedFinishSec"] is None


def test_build_live_and_stale():
    s = splits_of(*[412] * 5)
    assert stats.build(raw(s, 5.1, 2100, age=10), 10800, now=NOW)["status"] == "live"
    stale = stats.build(raw(s, 5.1, 2100, age=150), 10800, now=NOW)
    assert stale["status"] == "stale" and stale["text"]["updatedAgo"] == "2 min ago"


def test_build_finished():
    s = splits_of(*[410] * 26)
    p = stats.build(raw(s, 26.2, 26 * 410 + 82), 10800, now=NOW)
    assert p["status"] == "finished"
    assert p["projectedFinishSec"] == 26 * 410 + 82
    assert not any(g["current"] for g in p["segments"])


def test_demo_variants_build():
    for v in ("live", "stale", "finished", "waiting"):
        p = stats.build(stats.demo_raw(v, now=NOW), 10800, now=NOW)
        assert p["status"] == v
