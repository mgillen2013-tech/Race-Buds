# Race Buds

Friends and family record a voice note on a web page. It lands on your phone as an MMS,
and Siri plays it through your AirPods.

## Run it locally (no sending)
    pip install -r requirements.txt
    python app.py            # opens on http://localhost:5000, clips save to ./sent/
Microphone access needs https or localhost.

## Deploy (Render)
1. Push this folder to GitHub.
2. Render -> New Web Service -> pick the repo. Build command: `pip install -r requirements.txt`
   Start command: `gunicorn app:app --workers 1 --threads 4`
   (One worker matters: the 30-minute cooldown is kept in memory.)
3. Add the variables from `.env.example` under Environment.
4. Share `https://your-app.onrender.com/?key=YOUR_ACCESS_KEY` with your people.

## Gmail setup
Turn on 2-step verification, then create an App Password (Google Account -> Security).
Use that as SMTP_PASS. Your normal password won't work.

## Race morning
Start LiveTrack on the watch, copy the link, paste it into LIVETRACK_URL, redeploy.
