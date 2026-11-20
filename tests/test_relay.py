import base64
import io
import os
import subprocess
import sys
import threading
import time

import pytest
from werkzeug.serving import make_server

import app
import relay


@pytest.fixture
def relay_on(monkeypatch):
    monkeypatch.setattr(app, "RELAY_TOKEN", "secret-token")
    monkeypatch.setattr(app, "RELAY_TO", "+15555550123")
    monkeypatch.setattr(app, "RELAY", relay.RelayQueue())
    return app.app.test_client()


def test_queue_hands_out_once_until_claim_expires(monkeypatch):
    q = relay.RelayQueue()
    q.put(b"mp3", "Mom", "Lock in")
    first = q.next()
    assert first["from"] == "Mom" and q.next() is None  # being sent: not handed out twice
    monkeypatch.setattr(relay, "CLAIM_SEC", 0)
    assert q.next()["id"] == first["id"]  # Mac never confirmed: handed out again
    assert q.ack(first["id"]) and q.next() is None


def test_delivery_goes_to_queue_and_out_through_the_relay_endpoints(relay_on):
    c = relay_on
    app.deliver(b"ID3fake", "Mom", spoken=True)
    assert c.get("/relay/next").status_code == 404  # no token
    r = c.get("/relay/next", headers={"X-Relay-Token": "secret-token"})
    note = r.get_json()
    assert note["from"] == "Mom" and note["to"] == "+15555550123" and note["text"] == app.TEXT_WHEN_SPOKEN
    assert base64.b64decode(note["audio"]) == b"ID3fake"
    assert c.post(f"/relay/ack?id={note['id']}", headers={"X-Relay-Token": "secret-token"}).get_json()["ok"]
    assert c.get("/relay/next", headers={"X-Relay-Token": "secret-token"}).status_code == 204


def test_script_download_is_filled_in(relay_on):
    assert relay_on.get("/relay/script?token=wrong").status_code == 404
    body = relay_on.get("/relay/script?token=secret-token").get_data(as_text=True)
    assert "BASE = 'http://localhost'" in body and "TOKEN = 'secret-token'" in body
    compile(body, "mac_relay.py", "exec")


def test_mac_script_end_to_end(relay_on, tmp_path, monkeypatch):
    """Run the downloaded script against a real local server, with a fake osascript standing in for Messages."""
    server = make_server("127.0.0.1", 0, app.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        script = relay_on.get("/relay/script?token=secret-token").get_data(as_text=True)
        script = script.replace("BASE = 'http://localhost'", f"BASE = {base!r}")
        (tmp_path / "relay.py").write_text(script)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        sent = tmp_path / "sent.txt"
        fake = bin_dir / "osascript"
        fake.write_text(f'#!/bin/sh\ncat > /dev/null\necho "$2|$3|$4" >> {sent}\n')
        fake.chmod(0o755)
        app.deliver(b"ID3one", "Mom", spoken=True)
        app.deliver(b"ID3two", "Dad", spoken=True)
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", HOME=str(tmp_path),
                   NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
        proc = subprocess.Popen([sys.executable, str(tmp_path / "relay.py")], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + 15
        while time.time() < deadline and app.RELAY.pending():
            time.sleep(0.2)
        proc.terminate()
        out = proc.communicate(timeout=5)[0]
        lines = sent.read_text().splitlines()
        assert len(lines) == 2, out
        assert lines[0].startswith("+15555550123|" + app.TEXT_WHEN_SPOKEN + "|")
        files = sorted((tmp_path / "Pictures" / "RaceBuds").iterdir())
        assert {f.read_bytes() for f in files} == {b"ID3one", b"ID3two"}
        assert app.RELAY.pending() == 0
    finally:
        server.shutdown()
