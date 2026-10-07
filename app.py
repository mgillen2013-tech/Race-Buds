"""Race Buds: friends and family record a voice note, it lands on the runner's phone as an MMS.

Prototype delivery path: email -> Verizon MMS gateway (number@vzwpix.com).
To move to Twilio later, replace deliver() and keep everything else.
"""
import hmac
import os
import smtplib
import subprocess
import tempfile
import threading
import time
from email.message import EmailMessage
from pathlib import Path

import imageio_ffmpeg
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # reject uploads over 5 MB

# ---- Settings (all from environment variables, see .env.example) ----
RUNNER_NAME = os.environ.get("RUNNER_NAME", "M")
LIVETRACK_URL = os.environ.get("LIVETRACK_URL", "")
ACCESS_KEY = os.environ.get("ACCESS_KEY", "")  # optional: page + send require ?key=...
COOLDOWN_SECONDS = int(os.environ.get("COOLDOWN_SECONDS", "1800"))  # 30 minutes
MAX_CLIP_SECONDS = 30

DEST_ADDRESS = os.environ.get("DEST_ADDRESS", "")  # e.g. 6105852764@vzwpix.com
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")  # Gmail app password, not your login password
# Text Siri reads aloud before the clip. {name} is replaced with the sender's name.
MESSAGE_TEMPLATE = os.environ.get("MESSAGE_TEMPLATE", "From {name}")

# With DRY_RUN=1 (or no SMTP settings) clips are saved to ./sent instead of emailed.
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not (DEST_ADDRESS and SMTP_USER and SMTP_PASS)

# ---- Cooldown (in memory: run a single worker, and it resets if the server restarts) ----
_last_sent: dict[str, float] = {}
_lock = threading.Lock()


def reserve_slot(sender_key: str):
    """Return (ok, seconds_to_wait). Reserves the slot so double-taps can't slip through."""
    now = time.time()
    with _lock:
        last = _last_sent.get(sender_key)
        if last is not None and now - last < COOLDOWN_SECONDS:
            return False, int(COOLDOWN_SECONDS - (now - last)) + 1
        _last_sent[sender_key] = now
        return True, 0


def release_slot(sender_key: str):
    with _lock:
        _last_sent.pop(sender_key, None)


# ---- Audio ----
def to_mp3(raw: bytes, content_type: str) -> bytes:
    """Browsers record WebM or MP4/AAC; the phone needs MP3."""
    ext = ".mp4" if "mp4" in content_type else ".webm"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / f"in{ext}", Path(tmp) / "out.mp3"
        src.write_bytes(raw)
        subprocess.run(
            [ffmpeg, "-y", "-i", str(src), "-t", str(MAX_CLIP_SECONDS), "-vn",
             "-ac", "1", "-ar", "44100", "-b:a", "64k", str(dst)],
            check=True, capture_output=True, timeout=60,
        )
        return dst.read_bytes()


# ---- Delivery ----
def deliver(mp3: bytes, sender_name: str):
    if DRY_RUN:
        out = Path(__file__).parent / "sent"
        out.mkdir(exist_ok=True)
        (out / f"{int(time.time())}-{sender_name[:20].replace('/', '_')}.mp3").write_bytes(mp3)
        return
    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = DEST_ADDRESS
    msg["Subject"] = "Voice note"  # an empty subject + empty body got bounced by Verizon
    msg.set_content(MESSAGE_TEMPLATE.replace("{name}", sender_name))
    msg.add_attachment(mp3, maintype="audio", subtype="mpeg", filename="voice-note.mp3")
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)


# ---- Routes ----
def key_ok(supplied: str) -> bool:
    return not ACCESS_KEY or hmac.compare_digest(supplied or "", ACCESS_KEY)


@app.get("/")
def index():
    key = request.args.get("key", "")
    if not key_ok(key):
        return "This link isn't valid. Ask for the original link.", 403
    return render_template(
        "index.html", runner=RUNNER_NAME, livetrack_url=LIVETRACK_URL, key=key,
        max_seconds=MAX_CLIP_SECONDS, cooldown_minutes=COOLDOWN_SECONDS // 60,
    )


@app.post("/send")
def send():
    if not key_ok(request.form.get("key", "")):
        return jsonify(error="This link isn't valid."), 403

    name = " ".join(request.form.get("name", "").split())[:40]
    clip = request.files.get("audio")
    if not name:
        return jsonify(error="Add your name first."), 400
    if clip is None:
        return jsonify(error="No recording came through. Try again."), 400

    sender_key = name.lower()
    ok, wait = reserve_slot(sender_key)
    if not ok:
        return jsonify(error=f"You can send another in {max(1, wait // 60)} min.", retry_after=wait), 429

    try:
        mp3 = to_mp3(clip.read(), clip.mimetype or "")
        deliver(mp3, name)
    except Exception:
        app.logger.exception("send failed")
        release_slot(sender_key)  # a failed send shouldn't burn their turn
        return jsonify(error="Couldn't send that one. Try again."), 500
    return jsonify(ok=True)


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(debug=True, port=5000)
