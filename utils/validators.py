# validators.py
import os
from pydub import AudioSegment

MIN_BYTES = 80_000      # ~80KB : guard tiny/empty files
MIN_DURATION_S = 20     # stems shorter than this are suspicious
MIN_RMS = 5             # very low RMS => near-silence

EXPECTED = ["vocals.mp3", "drums.mp3", "bass.mp3", "other.mp3"]

def _rms_ok(path: str) -> bool:
    try:
        seg = AudioSegment.from_file(path)
        return seg.duration_seconds >= MIN_DURATION_S and seg.rms >= MIN_RMS
    except Exception:
        return False

def validate_stems(base: str) -> dict:
    """Return {'ok': bool, 'problems': {stem: reason}}"""
    problems = {}
    for name in EXPECTED:
        fp = os.path.join(base, name)
        if not os.path.exists(fp):
            problems[name] = "missing"
            continue
        if os.path.getsize(fp) < MIN_BYTES:
            problems[name] = "too_small"
            continue
        if not _rms_ok(fp):
            problems[name] = "silent_or_short"
    return {"ok": len(problems) == 0, "problems": problems}
