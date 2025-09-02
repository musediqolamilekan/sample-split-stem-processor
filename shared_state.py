import threading
import json

# In-memory store
_progress_store = {}
_progress_lock = threading.Lock()

def set_progress(session_id: str, data: dict):
    with _progress_lock:
        _progress_store[session_id] = json.dumps(data)

def get_progress(session_id: str):
    with _progress_lock:
        value = _progress_store.get(session_id)
        if value:
            return json.loads(value)
    return {"message": "Waiting...", "percent": 0}

def delete_progress(session_id: str):
    with _progress_lock:
        _progress_store.pop(session_id, None)
