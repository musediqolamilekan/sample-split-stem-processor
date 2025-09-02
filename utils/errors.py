# errors.py
import json, os, time
def log_failure(batch_id: str, track_id: str, reason: str, details: dict = None):
    os.makedirs("fail_logs", exist_ok=True)
    path = os.path.join("fail_logs", f"{batch_id}.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps({
            "ts": int(time.time()),
            "track_id": track_id,
            "reason": reason,
            "details": details or {}
        }) + "\n")
