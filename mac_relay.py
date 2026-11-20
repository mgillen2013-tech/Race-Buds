#!/usr/bin/env python3
"""Race Buds Mac relay: sends each new voice note to the runner's iPhone as an iMessage.

Download it from the app (the server fills in its address and token), then run it on a Mac whose
Messages app is signed in to a DIFFERENT Apple ID than the runner's phone (messages you send to
yourself don't notify):

    caffeinate -i python3 ~/racebuds_relay.py

caffeinate keeps the Mac awake. Leave the Terminal window open; Ctrl+C stops it.
The first time, macOS asks to let Terminal control Messages: click OK.
Uses only Python's standard library plus macOS's own curl and osascript.
"""
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

BASE = "__BASE__"    # filled in by the server when downloaded
TOKEN = "__TOKEN__"  # filled in by the server when downloaded
# Messages can only attach files from some folders (a macOS restriction), so notes go in Pictures.
FOLDER = Path.home() / "Pictures" / "RaceBuds"

SEND = """
on run argv
    set theTo to item 1 of argv
    set theText to item 2 of argv
    set theFile to (POSIX file (item 3 of argv)) as alias
    tell application "Messages"
        set svc to 1st account whose service type = iMessage
        set who to participant theTo of svc
        if theText is not "" then send theText to who
        send theFile to who
    end tell
end run
"""


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def curl(*args):
    """HTTP through macOS's curl (uses the system's certificates; Python's sometimes lack them)."""
    r = subprocess.run(["curl", "-sS", "--max-time", "30", "-H", f"X-Relay-Token: {TOKEN}", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"curl exited {r.returncode}")
    return r.stdout


def send_imessage(to, text, path):
    r = subprocess.run(["osascript", "-", to, text, str(path)], input=SEND, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())


def main():
    if "__" in BASE or "__" in TOKEN:
        sys.exit("Download this script from the app's /relay/script link so it has the address and token.")
    FOLDER.mkdir(parents=True, exist_ok=True)
    log(f"Race Buds relay running. Watching {BASE} for new notes. Ctrl+C to stop.")
    while True:
        try:
            body = curl(f"{BASE}/relay/next")
            if not body.strip():
                time.sleep(3)  # nothing waiting
                continue
            note = json.loads(body)
            path = FOLDER / f"note-{note['id']}-{int(time.time())}.mp3"
            path.write_bytes(base64.b64decode(note["audio"]))
            send_imessage(note["to"], note.get("text", ""), path)
            curl("-X", "POST", f"{BASE}/relay/ack?id={note['id']}")
            log(f"Sent note {note['id']} from {note['from']} to {note['to']}")
        except KeyboardInterrupt:
            log("Stopped.")
            return
        except Exception as exc:
            log(f"Problem: {exc}. Trying again in 10 s.")
            time.sleep(10)


if __name__ == "__main__":
    main()
