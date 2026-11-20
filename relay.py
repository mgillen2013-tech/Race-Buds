"""Hand-off queue for the Mac relay (Verizon shut down its email-to-text gateway in Nov 2026).

Notes are queued in memory; a script on the runner's Mac (mac_relay.py, served by /relay/script)
polls /relay/next, sends each note to the runner's iPhone as an iMessage, then confirms with /relay/ack.
A note handed out but not confirmed within CLAIM_SEC is handed out again, so a Mac that crashes
mid-send doesn't lose it (at worst a note arrives twice). The queue is lost if the server restarts.
"""
import itertools
import threading
import time

CLAIM_SEC = 120
KEEP_SEC = 6 * 3600  # undelivered notes older than this are dropped


class RelayQueue:
    def __init__(self):
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._notes = []  # oldest first: {"id", "from", "text", "mp3", "created", "claimed_at"}
        self.last_poll = 0.0

    def put(self, mp3: bytes, sender: str, text: str) -> int:
        with self._lock:
            note_id = next(self._ids)
            self._notes.append({"id": note_id, "from": sender, "text": text, "mp3": mp3,
                                "created": time.time(), "claimed_at": 0.0})
            return note_id

    def next(self):
        """The oldest note not currently being sent, or None. Marks it as handed out."""
        now = time.time()
        with self._lock:
            self.last_poll = now
            self._notes = [n for n in self._notes if now - n["created"] < KEEP_SEC]
            for n in self._notes:
                if now - n["claimed_at"] >= CLAIM_SEC:
                    n["claimed_at"] = now
                    return dict(n)
        return None

    def ack(self, note_id: int) -> bool:
        with self._lock:
            before = len(self._notes)
            self._notes = [n for n in self._notes if n["id"] != note_id]
            return len(self._notes) < before

    def pending(self) -> int:
        with self._lock:
            return len(self._notes)
