# Race Buds

Friends and family follow the runner's marathon and send voice notes. Each note lands on the runner's
iPhone as an MMS with an MP3 attachment, and Siri (Announce Notifications) reads it aloud through AirPods
while the phone is locked, hands-free. Built for the runner's November 2026 marathon.

## How it works
- `templates/index.html`: mobile-first "Bib" design (navy page, white race-bib card). Top: LIVE pill and
  "Mile X of 26.2". Bib: runner name, progress bar, projected finish vs goal, HR/pace/distance/elapsed,
  segment table. Bottom bar (pinned): name field (required, saved in localStorage), "Record a cheer"
  (30 s max), preview, Send. Polls `/api/stats` every 10 s while visible. No location shown on purpose.
- `stats.py`: pure functions for the stats payload: formatting, projected finish (elapsed + remaining x
  mean of last 3 miles), segments (blocks of `SEGMENT_MILES`, pace = time / distance), status
  waiting/live/stale (>90 s old)/finished, and demo data. Tests in `tests/test_stats.py` (`pytest`).
- `app.py` (Flask): `/` page (needs `?key=ACCESS_KEY`), `/send` upload endpoint, `/api/stats` (same key),
  `/healthz`. Real LiveTrack data is not wired in yet: without `DEMO_STATS=1` stats are always "waiting".
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
`GOAL_TIME` (default 3:00:00), `SEGMENT_MILES` (default 4), `DEMO_STATS` (local only; ignored when `RENDER` is set).
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
  `Livetrack-Csrf-Token` header. Indoors with no GPS fix, `trackPoints` was empty; the fields inside a
  track point are not seen yet. Garmin also has `/api/messages/spectator/audio` (its own spectator
  voice messages), worth a look.
- Spoken intro: gTTS is an unofficial Google TTS wrapper. It could not be tested in the build sandbox;
  failure falls back to the plain text message, so notes are never blocked. Voice is somewhat robotic.

## Open items / ideas
1. Twilio: dedicated number saved in the runner's contacts as "Race Buds" (Siri announces the contact
   name). Start carrier registration early, since approval can take days or weeks. Must test whether Siri
   plays a Twilio MMS audio attachment the same way.
2. LiveTrack: each session has its own link. Idea: make a dedicated inbox a LiveTrack contact and have the
   app read the email to pick up the new session link automatically (or add a password-protected page to
   paste the link without redeploying).
3. Possible custom dashboard from LiveTrack data. There is no official LiveTrack API; community projects
   reverse-engineer the page. Spike first: check what the page loads in the browser network tab. Keep the
   plain LiveTrack link as a fallback. Idea: projected finish vs the runner's goal.
4. Idea: show the runner's current song (Spotify's now-playing API, or Last.fm for Apple Music).
5. Dress rehearsal on a long run: phone in a pocket or belt, moving, LiveTrack running, a few notes from family.
   Race crowds can drop cell signal, so test on a busy day if possible.
6. Rotate the Gmail app password after any chat or log exposure, and keep `ACCESS_KEY` private.
