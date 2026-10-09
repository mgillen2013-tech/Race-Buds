# Race Buds

Friends and family follow the runner's marathon and send voice notes. Each note lands on the runner's
iPhone as an MMS with an MP3 attachment, and Siri (Announce Notifications) reads it aloud through AirPods
while the phone is locked, hands-free. Built for the runner's November 2026 marathon.

## How it works
- `templates/index.html`: mobile-first "Bib" design (navy page, white race-bib card). Top: LIVE pill and
  "Mile X of 26.2". Bib: runner name, progress bar, projected finish (no goal shown, by request), HR/avg pace (whole run)/distance/elapsed,
  segment table. Bottom bar (pinned): name field (required, saved in localStorage), "Record a cheer"
  (30 s max), preview, Send. Polls `/api/stats` every 10 s while visible. No location shown on purpose.
- `stats.py`: pure functions for the stats payload: formatting, projected finish (elapsed + remaining x
  mean of last 3 miles), segments (blocks of `SEGMENT_MILES`, pace = time / distance), status
  waiting/live/stale (>90 s old)/finished, and demo data. Tests in `tests/test_stats.py` (`pytest`).
- `app.py` (Flask): `/` page (needs `?key=ACCESS_KEY`), `/send` upload endpoint, `/api/stats` (same key),
  `/healthz`. Stats come from `livetrack.py` (or demo data with `DEMO_STATS=1`).
- `livetrack.py`: finds the newest LiveTrack link in the `SMTP_USER` Gmail inbox over IMAP (same app
  password; checked every 60 s with no live session, every 5 min while following a live one; `LIVETRACK_URL` is a
  fallback), then pulls only new track points from Garmin (cache 5 s, backoff 10 s to 5 min, one fetch at a
  time). Drops location on arrival. Computes mile splits by interpolation and pace over the last 60 s.
  A stopped watch (session `end` in the past) shows as finished for 2 h, then back to waiting.
  Send flow: validate key and name -> per-name cooldown (`COOLDOWN_SECONDS`, default 0 = off; in memory) -> optional spoken intro
  ("From <name>", gTTS) -> ffmpeg (bundled via imageio-ffmpeg) converts WebM/MP4 to mono 64 kbps MP3 ->
  `deliver()` emails it via Gmail SMTP to `<runner number>@vzwpix.com` (Verizon's email-to-MMS gateway).
- Hosted on Render (paid instance, required, see below), deployed from a private GitHub repo.
  Start command: `gunicorn app:app --workers 1 --threads 4` (one worker: the cooldown is in memory and
  resets on restart).
- `deliver()` is the only delivery-specific code. The planned replacement is Twilio MMS.

## Config (environment variables, see .env.example; never commit real values)
`DEST_ADDRESS`, `SMTP_USER`, `SMTP_PASS` (Gmail app password), `RUNNER_NAME`, `LIVETRACK_URL`,
`ACCESS_KEY`, `COOLDOWN_SECONDS`, `SPOKEN_INTRO`, `INTRO_TEMPLATE`, `TEXT_WHEN_SPOKEN`, `MESSAGE_TEMPLATE`,
`SEGMENT_MILES` (default 4), `IMAP_HOST` (default imap.gmail.com), `DEMO_STATS` (local only; ignored when `RENDER` is set).
With no SMTP settings (or `DRY_RUN=1`) clips are saved to `./sent/` instead of emailed.

## Run locally (Mac)
```
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py        # open http://127.0.0.1:5000 (not "localhost": macOS AirPlay Receiver can answer on 5000)
```
Turn Mac Bluetooth off while testing: AirPods hop to the Mac when it records, and then the phone has
nothing to announce through.

## Findings from testing (don't relearn these)
- Siri reads an MMS's text aloud, then plays the MP3 attachment. Confirmed with AirPods in, phone locked.
- The Verizon gateway splits an email into a text message and an attachment message, and the order they
  arrive varies, so the attachment sometimes plays before "From <name>". Fix: speak the name inside the
  audio itself (gTTS intro prepended with ffmpeg), so order is guaranteed.
- A message with an empty subject and a blank body was bounced by Verizon ("inbox is full"). Cause unknown,
  so a subject is always set.
- A blank text body (spoken intro on) made Siri say "a message I can't read" before the clip. So the
  body is never blank: `TEXT_WHEN_SPOKEN` defaults to "Lock in" (a blank value falls back to it).
- MP3 attachments worked; the first M4A attempt bounced.
- Verizon's gateway is flaky (spam filtering) and was reported to be shutting down March 31, 2027.
- Render's free tier blocks outbound SMTP (ports 465/587). A paid instance is required for Gmail SMTP.
- LiveTrack data (checked Oct 2026): the old `/services/session/<id>/trackpoints` endpoint used by
  github.com/Novex/garmin-livetrack-obs now 404s. The current site (Next.js) uses
  `GET /api/v2/sessions/<id>?token=<token>` (session info: name, start/end, `postTrackPointFrequency` 15 s)
  and `GET /api/sessions/<id>/track-points/common?token=<token>` (`{"trackPoints": [...]}`, paged with
  `begin=`). Both return 403 unless you first GET the session page
  (`/session/<id>/token/<token>`), keep its cookies, and send its `<meta name="csrf-token">` value as the
  `Livetrack-Csrf-Token` header. Indoors with no GPS fix, `trackPoints` was empty.
  Real run (Oct 9): one point every 10 s, posted in batches about every 15 s, so data is ~15-20 s behind.
  Point fields: `dateTime`, `reportedTime`, `totalDistanceMeters`, `totalDurationSecs`, `heartRateBeatsPerMin`,
  `speedMetersPerSec` (0 when stopped), `cadenceCyclesPerMin`, `powerWatts`, `pointStatus`
  (MOVING/STATIONARY), `altitude`, `position` (never show it). No mile splits: compute them by
  interpolating the time each mile is crossed. A session link expires 24 h after it starts. Garmin also has `/api/messages/spectator/audio` (its own spectator
  voice messages), worth a look.
- Spoken intro: gTTS is an unofficial Google TTS wrapper. It could not be tested in the build sandbox;
  failure falls back to the plain text message, so notes are never blocked. Voice is somewhat robotic.

## Open items / ideas
1. Twilio: dedicated number saved in the runner's contacts as "Race Buds" (Siri announces the contact
   name). Start carrier registration early, since approval can take days or weeks. Must test whether Siri
   plays a Twilio MMS audio attachment the same way.
2. LiveTrack link pickup from email is built (see `livetrack.py`). The runner declined a paste-the-link page
   and any "Open Garmin LiveTrack" link on the page.
   Untested until a real run with the deployed app: the IMAP search (Garmin's sender and email format).
3. Possible custom dashboard from LiveTrack data. There is no official LiveTrack API; community projects
   reverse-engineer the page. Built (see `livetrack.py`). The plain LiveTrack link was removed from the
   page at the runner's request. Projected finish is shown; the runner does not want a goal time on the page.
4. Idea: show the runner's current song (Spotify's now-playing API, or Last.fm for Apple Music).
5. Dress rehearsal on a long run: phone in a pocket or belt, moving, LiveTrack running, a few notes from family.
   Race crowds can drop cell signal, so test on a busy day if possible.
6. Rotate the Gmail app password after any chat or log exposure, and keep `ACCESS_KEY` private.
