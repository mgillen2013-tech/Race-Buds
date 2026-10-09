"""Live data from Garmin LiveTrack, turned into the raw dict that stats.build() expects.

There is no official LiveTrack API. This reads the same JSON the LiveTrack web page reads (see the
LiveTrack findings in CLAUDE.md), so it can break if Garmin changes their site. Failures never raise
to the page: the last good data is kept and the page shows it as "delayed" once it is over 90 s old.

The session link changes every run. It is picked up from the newest Garmin LiveTrack email in the
Gmail inbox the app already sends from (IMAP, same app password), with LIVETRACK_URL as a fallback.
Location is dropped as soon as points arrive and never leaves this module.
"""
import email
import http.cookiejar
import imaplib
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email import policy

log = logging.getLogger(__name__)

BASE = "https://livetrack.garmin.com"
URL_RE = re.compile(r"livetrack\.garmin\.com/session/([0-9a-fA-F-]{36})/token/([0-9A-Za-z]+)")
METERS_PER_MILE = 1609.344
SHOW_AFTER_END = timedelta(hours=12)  # keep showing a stopped run's final numbers this long
PACE_WINDOW_SEC = 60  # current pace = distance covered over about the last minute
KEEP_FIELDS = ("dateTime", "totalDistanceMeters", "totalDurationSecs", "heartRateBeatsPerMin")
USER_AGENT = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")


# ---- Finding the session link ----
def parse_session_url(text):
    """Return (session_id, token) from any text containing a LiveTrack link, or None."""
    m = URL_RE.search(text or "")
    return (m.group(1), m.group(2)) if m else None


def session_from_message(msg):
    """Find a LiveTrack link in an email.message.EmailMessage (plain text or HTML part)."""
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            try:
                found = parse_session_url(part.get_content())
            except Exception:
                continue
            if found:
                return found
    return None


def newest_session_from_gmail(user, password, host="imap.gmail.com"):
    """Look through the last two days of mail from Garmin, newest first, for a LiveTrack link."""
    since = (date.today() - timedelta(days=2)).strftime("%d-%b-%Y")
    with imaplib.IMAP4_SSL(host, timeout=20) as box:
        box.login(user, password)
        for folder in ("INBOX", '"[Gmail]/All Mail"'):
            typ, _ = box.select(folder, readonly=True)
            if typ != "OK":
                continue
            typ, data = box.search(None, "FROM", '"garmin"', "SINCE", since)
            if typ != "OK":
                continue
            for msg_id in reversed(data[0].split()[-15:]):
                typ, parts = box.fetch(msg_id, "(BODY.PEEK[])")  # PEEK: don't mark it read
                if typ != "OK" or not parts or not isinstance(parts[0], tuple):
                    continue
                found = session_from_message(email.message_from_bytes(parts[0][1], policy=policy.default))
                if found:
                    return found
    return None


# ---- Turning track points into stats input ----
def _ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def points_to_raw(points):
    """Track points (oldest first) -> {"updatedAt", "distanceMi", "elapsedSec", "paceSecPerMi",
    "heartRate", "splits"}. Mile splits are found by interpolating when each mile was crossed."""
    pts = [p for p in points if p.get("totalDistanceMeters") is not None and p.get("totalDurationSecs") is not None]
    if not pts:
        return None
    last = pts[-1]
    dist = [p["totalDistanceMeters"] / METERS_PER_MILE for p in pts]
    secs = [float(p["totalDurationSecs"]) for p in pts]

    splits, prev_t, i = [], 0.0, 0
    hr_bucket = []
    for mile in range(1, int(dist[-1]) + 1):
        while dist[i] < mile:  # dist[-1] >= mile, so this stops in range
            hr = pts[i].get("heartRateBeatsPerMin")
            if hr:
                hr_bucket.append(hr)
            i += 1
        if i == 0 or dist[i] == dist[i - 1]:
            t = secs[i]
        else:
            frac = (mile - dist[i - 1]) / (dist[i] - dist[i - 1])
            t = secs[i - 1] + frac * (secs[i] - secs[i - 1])
        splits.append({"mile": mile, "secs": round(t - prev_t),
                       "hr": round(sum(hr_bucket) / len(hr_bucket)) if hr_bucket else None})
        prev_t, hr_bucket = t, []

    # Current pace over the last minute or so (speed reads 0 at every stop, so don't use it).
    j = len(pts) - 1
    while j > 0 and secs[-1] - secs[j] < PACE_WINDOW_SEC:
        j -= 1
    d_mi, d_t = dist[-1] - dist[j], secs[-1] - secs[j]
    pace = round(d_t / d_mi) if d_mi > 0.03 and d_t > 0 else None

    return {
        "updatedAt": last["dateTime"],
        "distanceMi": round(dist[-1], 2),
        "elapsedSec": round(secs[-1]),
        "paceSecPerMi": pace,
        "heartRate": last.get("heartRateBeatsPerMin") or None,
        "splits": splits,
    }


# ---- Talking to Garmin ----
class LiveTrack:
    """Keeps the current session's points in memory and fetches only new ones.

    raw() is safe to call on every page request: results are cached for CACHE_SEC so many viewers
    don't multiply requests to Garmin, errors back off (10 s doubling to 5 min), and if another
    request is already fetching, the cached value is returned right away.
    """
    CACHE_SEC = 5
    EMAIL_EVERY_SEC = 60        # while there is no session
    EMAIL_EVERY_LIVE_SEC = 300  # while following one, in case a newer run started

    def __init__(self, find_session=None, fallback_url=""):
        self._find_session = find_session  # callable -> (id, token) or None
        self._fallback = parse_session_url(fallback_url)
        self._lock = threading.Lock()
        self._session = None
        self._session_end = None
        self._points = []
        self._raw = None
        self._csrf = ""
        self._opener = None
        self._fetched_at = 0.0
        self._email_at = 0.0
        self._info_at = 0.0
        self._backoff_until = 0.0
        self._errors = 0

    @property
    def url(self):
        s = self._session or self._fallback
        return f"{BASE}/session/{s[0]}/token/{s[1]}" if s else ""

    def raw(self):
        if not self._lock.acquire(blocking=False):
            return self._raw
        try:
            now = time.time()
            if now - self._fetched_at < self.CACHE_SEC or now < self._backoff_until:
                return self._raw
            self._fetched_at = now
            try:
                self._check_session(now)
                if self._session:
                    if not (self._ended() and self._raw):  # nothing new arrives after the end
                        self._pull_points()
                    if self._ended() and datetime.now(timezone.utc) > self._session_end + SHOW_AFTER_END:
                        self._raw = None  # an old run: back to the waiting screen
                    else:
                        self._raw = points_to_raw(self._points)
                        if self._raw:
                            self._raw["ended"] = self._ended()
                self._errors = 0
            except Exception as exc:
                self._errors += 1
                self._backoff_until = now + min(300, 10 * 2 ** (self._errors - 1))
                log.warning("LiveTrack fetch failed (%s); keeping last data", exc)
            return self._raw
        finally:
            self._lock.release()

    def _ended(self):
        return bool(self._session_end and datetime.now(timezone.utc) > self._session_end)

    # -- session --
    def _check_session(self, now):
        every = self.EMAIL_EVERY_LIVE_SEC if self._session else self.EMAIL_EVERY_SEC
        found = None
        if self._find_session and now - self._email_at >= every:
            self._email_at = now
            try:
                found = self._find_session()
            except Exception as exc:
                log.warning("Couldn't check email for a LiveTrack link (%s)", exc)
        if not found and not self._session:
            found = self._fallback
        if found and found != self._session:
            log.info("Following LiveTrack session %s", found[0])
            self._session, self._points, self._raw = found, [], None
            self._session_end, self._opener, self._info_at = None, None, 0.0

    # -- HTTP --
    def _open_page(self):
        """The API answers 403 unless we hold the page's cookies and send its CSRF token."""
        jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        sid, token = self._session
        req = urllib.request.Request(f"{BASE}/session/{sid}/token/{token}", headers={"User-Agent": USER_AGENT})
        with self._opener.open(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", "replace")
        m = re.search(r'name="csrf-token" content="([^"]+)"', html)
        if not m:
            raise RuntimeError("no csrf-token on the LiveTrack page (did Garmin change it?)")
        self._csrf = m.group(1)

    def _get_json(self, path, params, retry=True):
        if self._opener is None:
            self._open_page()
        req = urllib.request.Request(
            f"{BASE}{path}?{urllib.parse.urlencode(params)}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json", "Livetrack-Csrf-Token": self._csrf},
        )
        try:
            with self._opener.open(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403) and retry:
                self._opener = None  # cookies or token went stale: reload the page once
                return self._get_json(path, params, retry=False)
            raise

    def _pull_points(self):
        sid, token = self._session
        if time.time() - self._info_at >= 60:  # "end" moves up when the watch stops
            self._info_at = time.time()
            info = self._get_json(f"/api/v2/sessions/{sid}", {"token": token})
            if info.get("end"):
                self._session_end = _ts(info["end"])
        for _ in range(30):  # pages; each holds many points
            params = {"token": token}
            if self._points:
                last = _ts(self._points[-1]["dateTime"]) + timedelta(milliseconds=1)
                params["begin"] = last.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            new = self._get_json(f"/api/sessions/{sid}/track-points/common", params).get("trackPoints") or []
            new = [{k: p.get(k) for k in KEEP_FIELDS} for p in new if p.get("dateTime")]  # drops location
            if self._points:
                new = [p for p in new if _ts(p["dateTime"]) > _ts(self._points[-1]["dateTime"])]
            if not new:
                return
            self._points.extend(sorted(new, key=lambda p: p["dateTime"]))
