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

## Gmail setup
Turn on 2-step verification, then create an App Password (Google Account -> Security).
Use that as SMTP_PASS. Your normal password won't work.

## Race morning
Nothing to paste. Once, beforehand: in the Garmin Connect app, add the Gmail address in SMTP_USER as a
LiveTrack contact. On race morning just start LiveTrack: Garmin emails the link to that inbox, and the
app finds the newest one (checks every minute) and shows live stats. LIVETRACK_URL is only a fallback.
