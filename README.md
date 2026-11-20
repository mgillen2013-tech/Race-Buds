# Race Buds

Friends and family record a voice note on a web page. It lands on your phone as an MMS,
and Siri plays it through your AirPods.

## Run it locally (no sending)
    pip install -r requirements.txt
    python app.py            # opens on http://localhost:5000, clips save to ./sent/
Microphone access needs https or localhost.

To see the page with sample race numbers (no run needed):
    DEMO_STATS=1 RUNNER_NAME=Michael python app.py
Then open http://127.0.0.1:5000. Add `?demo=waiting`, `?demo=stale` or `?demo=finished` to see the
other states. Demo mode shows a yellow DEMO tag and is ignored on Render.

## Tests
    pip install -r requirements-dev.txt
    pytest

## Deploy (Render)
1. Push this folder to GitHub.
2. Render -> New Web Service -> pick the repo. Build command: `pip install -r requirements.txt`
   Start command: `gunicorn app:app --workers 1 --threads 4`
   (One worker matters: the optional cooldown, `COOLDOWN_SECONDS`, is kept in memory.)
3. Add the variables from `.env.example` under Environment.
4. Share `https://your-app.onrender.com/?key=YOUR_ACCESS_KEY` with your people.

## Mac relay (how notes reach the phone)
Verizon shut down its email-to-text gateway in Nov 2026, so notes now go through a Mac:
1. On the Mac, sign Messages in to a *second* Apple ID (not the runner's), so the phone gets a notification.
   On the iPhone, save that Apple ID as a contact named "Race Buds".
2. In Render, set `RELAY_TOKEN` (output of `openssl rand -hex 24`) and `RELAY_TO` (runner's +1 number).
3. On the Mac, in Terminal:
       curl -s "https://YOUR-APP.onrender.com/relay/script?token=RELAY_TOKEN" -o ~/racebuds_relay.py
       caffeinate -i python3 ~/racebuds_relay.py
   Allow Terminal to control Messages when asked. Keep the Mac plugged in, lid open, Terminal open.
Notes wait on the server (up to 6 h) while the Mac is off, and are lost if the server restarts.

## Gmail setup
Turn on 2-step verification, then create an App Password (Google Account -> Security).
Use that as SMTP_PASS. Your normal password won't work.

## Race morning
Nothing to paste. Once, beforehand: in the Garmin Connect app, add the Gmail address in SMTP_USER as a
LiveTrack contact. On race morning just start LiveTrack: Garmin emails the link to that inbox, and the
app finds the newest one (checks every minute) and shows live stats. LIVETRACK_URL is only a fallback.
