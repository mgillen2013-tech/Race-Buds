from email.message import EmailMessage

import livetrack

M = livetrack.METERS_PER_MILE
SID = "b14672b1-12b5-8979-a3d0-1b6289657200"


def pt(sec, miles, hr=150):
    return {"dateTime": f"2026-11-01T14:{sec // 60:02d}:{sec % 60:02d}.000Z",
            "totalDistanceMeters": miles * M, "totalDurationSecs": sec, "heartRateBeatsPerMin": hr}


def test_parse_session_url():
    text = f"Follow along: https://livetrack.garmin.com/session/{SID}/token/98FD5F34D3F164AF883BAE5C547B0F1 now"
    assert livetrack.parse_session_url(text) == (SID, "98FD5F34D3F164AF883BAE5C547B0F1")
    assert livetrack.parse_session_url("no link here") is None


def test_session_from_html_email():
    msg = EmailMessage()
    msg["From"] = "Garmin <noreply@garmin.com>"
    msg.set_content("plain part without the link")
    msg.add_alternative(f'<a href="https://livetrack.garmin.com/session/{SID}/token/ABC123">Watch</a>', subtype="html")
    assert livetrack.session_from_message(msg) == (SID, "ABC123")


def test_steady_pace_splits():
    # 7:00 /mi steady, a point every 30 s, for 2.5 miles
    pts = [pt(s, s / 420) for s in range(0, 1051, 30)]
    raw = livetrack.points_to_raw(pts)
    assert [s["secs"] for s in raw["splits"]] == [420, 420]
    assert raw["paceSecPerMi"] == 420
    assert raw["distanceMi"] == 2.5 and raw["elapsedSec"] == 1050


def test_split_interpolates_between_points():
    # mile 1 is crossed halfway between the points at 400 s (0.9 mi) and 500 s (1.1 mi)
    raw = livetrack.points_to_raw([pt(0, 0), pt(400, 0.9), pt(500, 1.1)])
    assert raw["splits"][0]["secs"] == 450


def test_split_hr_is_mean_of_that_mile():
    pts = [pt(0, 0, hr=140), pt(200, 0.5, hr=150), pt(400, 1.0, hr=160), pt(600, 1.5, hr=170)]
    raw = livetrack.points_to_raw(pts)
    assert raw["splits"][0]["hr"] == 145  # points before the mile 1 crossing: 140, 150
    assert raw["heartRate"] == 170


def test_pace_ignores_standing_still():
    # stopped at the end (distance flat for 60 s): no pace rather than a wild number
    pts = [pt(0, 0), pt(60, 0.15), pt(90, 0.15), pt(120, 0.15)]
    assert livetrack.points_to_raw(pts)["paceSecPerMi"] is None


def test_no_points():
    assert livetrack.points_to_raw([]) is None
