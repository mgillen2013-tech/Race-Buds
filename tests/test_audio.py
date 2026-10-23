import struct
import subprocess

import imageio_ffmpeg

import app

FF = imageio_ffmpeg.get_ffmpeg_exe()


def seconds(mp3: bytes, tmp_path) -> float:
    f = tmp_path / "out.mp3"
    f.write_bytes(mp3)
    err = subprocess.run([FF, "-i", str(f), "-f", "null", "-"], capture_output=True, text=True).stderr
    t = [line for line in err.splitlines() if "time=" in line][-1].split("time=")[1].split()[0]
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def iphone_like_mp4(tmp_path, secs=10, claimed=2) -> bytes:
    """An AAC MP4 whose edit list claims only `claimed` seconds, like some iPhone Safari recordings."""
    f = tmp_path / "in.mp4"
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}",
                    "-ar", "48000", "-ac", "1", "-c:a", "aac", str(f)], check=True)
    b = bytearray(f.read_bytes())
    timescale = struct.unpack(">I", b[b.find(b"mvhd") + 16:b.find(b"mvhd") + 20])[0]
    j = b.find(b"elst")
    assert j > 0 and b[j + 4] == 0  # version 0 edit list
    b[j + 12:j + 16] = struct.pack(">I", claimed * timescale)
    return bytes(b)


def test_iphone_mp4_is_not_cut_short(tmp_path):
    raw = iphone_like_mp4(tmp_path)
    assert seconds(app.to_mp3(raw, "audio/mp4"), tmp_path) > 9.5


def test_iphone_mp4_with_spoken_intro_is_not_cut_short(tmp_path):
    raw = iphone_like_mp4(tmp_path)
    intro = tmp_path / "intro.mp3"
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=1.5",
                    "-ar", "24000", "-ac", "1", str(intro)], check=True)
    assert seconds(app.to_mp3(raw, "audio/mp4", intro.read_bytes()), tmp_path) > 11
