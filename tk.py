from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import asyncio
import shutil
import os
import json
import traceback
import copy
import webbrowser
import threading
from datetime import datetime  

from shared_state import set_progress, get_progress, delete_progress
from dispatch_download import process_all_tracks
from tunebat_helper import get_bpm_key

app = FastAPI(title="Stem Splitter & YouTube Scheduler")
templates = Jinja2Templates(directory="templates")

CLIENT_ID = "fbf9f3a2da0b44758a496ca7fa8a9290"
CLIENT_SECRET = "c47363028a7c478285fe1e27ecb4428f"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- Pin Queue (for manual pinning workflow) ----------
PIN_QUEUE_FILE = os.path.join(BASE_DIR, "pin_queue.jsonl")

def _read_pin_queue():
    items = []
    if os.path.exists(PIN_QUEUE_FILE):
        with open(PIN_QUEUE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    return items

def _write_pin_queue(items):
    with open(PIN_QUEUE_FILE, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

# ---------- Models ----------
class StemRequest(BaseModel):
    track_id: str
    channels: List[str]
    yt: bool = False
    ec2: bool = False
    trim: bool = False
    schedule_start_time: Optional[str] = None
    schedule_interval_minutes: Optional[int] = 60
    timezone: Optional[str] = "UTC"
    privacy: Optional[str] = "private"
    made_for_kids: Optional[bool] = False
    tags: Optional[List[str]] = Field(default_factory=list)
    description: Optional[str] = ""
    monetize: Optional[bool] = False
    genre: Optional[str] = "Hip-Hop"
    trim_track: Optional[bool] = False
    trim_length: Optional[int] = 72
    # UI toggle: "acapella" | "drumz" | "none"
    playlist_selection: Optional[str] = "none"

# ---------- Routes ----------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/progress/{session_id}")
async def progress_stream(session_id: str):
    async def event_generator():
        while True:
            data = get_progress(session_id) or {"message": "", "percent": 0, "meta": {}}
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/reset-progress/{session_id}")
def reset_progress(session_id: str):
    delete_progress(session_id)
    return {"message": "Progress reset for " + session_id}

def extract_spotify_id(raw: str) -> str:
    return raw.split("/")[-1].split("?")[0] if "spotify.com" in raw else raw

def get_all_track_ids(playlist_id: str) -> List[str]:
    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    ))
    ids = []
    offset = 0
    while True:
        items = sp.playlist_tracks(playlist_id, limit=100, offset=offset).get("items", [])
        if not items:
            break
        for item in items:
            track = item.get("track")
            if track and track.get("id"):
                ids.append(track["id"])
        offset += 100
    return ids

@app.post("/cleanup")
async def cleanup_files():
    try:
        for folder in ["MP3", "separated", "Thumbnails", "tunebat_debug"]:
            path = os.path.join(BASE_DIR, folder)
            if os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)
        cache_file = os.path.join(BASE_DIR, ".cache")
        if os.path.exists(cache_file):
            os.remove(cache_file)
        return {"status": "success", "message": "Cleaned up!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/split")
def split_and_schedule(request: StemRequest):
    input_id = extract_spotify_id(request.track_id)
    shared_args = {
        "yt": request.yt,
        "ec2": request.ec2,
        "trim": request.trim,
        "schedule_start_time": request.schedule_start_time,
        "timezone": request.timezone,
        "schedule_interval_minutes": request.schedule_interval_minutes,
        "privacy": request.privacy,
        "made_for_kids": request.made_for_kids,
        "tags": request.tags,
        "description": request.description,
        "monetize": request.monetize,
        "genre": request.genre,
        "trim_track": request.trim_track,
        "trim_length": request.trim_length,
        # Pass to uploader for playlist auto-add
        "playlist_selection": (request.playlist_selection or "none").strip().lower(),
    }

    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    ))

    try:
        _ = sp.playlist(input_id)
        track_ids = get_all_track_ids(input_id)
        is_playlist = True
    except Exception:
        track_ids = [input_id]
        is_playlist = False

    batch = []
    sessions = []

    for idx, track_id in enumerate(track_ids):
        session_id = f"{input_id}__{track_id}"
        sessions.append(session_id)
        info = sp.track(track_id)
        artist, title = info["artists"][0]["name"], info["name"]
        batch.append((title, artist, track_id))
        set_progress(session_id, {
            "message": "🟡 Preparing track metadata...",
            "percent": 0,
            "meta": {
                "track_id": track_id,
                "title": title,
                "artist": artist,
                "channels": request.channels,
                "playlist_id": input_id,
                "index": idx + 1,
                "total_tracks": len(track_ids)
            }
        })

    def run_full_pipeline():
        bpm_key_map = {}
        for title, artist, track_id in batch:
            bpm, key = get_bpm_key(title, artist, track_id)
            bpm_key_map[track_id] = (bpm, key)

        per_track_args = {}
        for idx, (title, artist, track_id) in enumerate(batch):
            bpm, key = bpm_key_map.get(track_id, (0, "Unknown"))
            args = copy.deepcopy(shared_args)
            args["bpm"] = bpm
            args["key"] = key
            args["global_artist_index"] = idx
            per_track_args[track_id] = args

        process_all_tracks(
            track_ids,
            request.channels,
            per_track_args=per_track_args,
            session_id=input_id,
            max_concurrent=2
        )

    threading.Thread(target=run_full_pipeline, daemon=True).start()

    return {
        "message": "Playlist processing started" if is_playlist else "Single track processing started",
        "tracks_processed": len(track_ids),
        "channels": request.channels,
        "session_ids": sessions
    }

# ---------- Pin Queue Endpoints ----------
@app.get("/pin-queue")
def list_pin_queue():
    items = _read_pin_queue()
    pending = [i for i in items if not i.get("pinned")]
    return {"pending": pending, "total": len(items), "pending_count": len(pending)}

@app.post("/pin-queue/mark")
async def mark_pinned(payload: dict):
    vid = payload.get("video_id")
    if not vid:
        raise HTTPException(status_code=400, detail="video_id is required")
    items = _read_pin_queue()
    updated = False
    for it in items:
        if it.get("video_id") == vid:
            it["pinned"] = True
            it["pinned_at"] = datetime.utcnow().isoformat() + "Z"
            updated = True
            break
    if updated:
        _write_pin_queue(items)
    return {"ok": updated}

@app.get("/pin-queue/ui", response_class=HTMLResponse)
def pin_queue_ui():
    items = _read_pin_queue()
    pending = [i for i in items if not i.get("pinned")]
    rows = "".join(
        f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #333">{i.get('channel','')}</td>
          <td style="padding:8px;border-bottom:1px solid #333">{i.get('title','')}</td>
          <td style="padding:8px;border-bottom:1px solid #333"><code>{i.get('video_id','')}</code></td>
          <td style="padding:8px;border-bottom:1px solid #333"><pre style="white-space:pre-wrap;margin:0">{i.get('comment','')}</pre></td>
          <td style="padding:8px;border-bottom:1px solid #333">
            <button onclick="markPinned('{i.get('video_id','')}')" style="padding:6px 10px;border-radius:8px;border:none;background:#00aaff;color:#fff;cursor:pointer">Mark Pinned</button>
          </td>
        </tr>
        """
        for i in pending
    )

    html = f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>Pin Queue</title>
      </head>
      <body style="background:#0b0f1a;color:#eaeaea;font-family:sans-serif;padding:24px">
        <h2 style="margin-top:0">Pinned Comment Queue</h2>
        <p>These videos have an auto-posted CTA comment but still need manual pinning in YouTube Studio.</p>
        <table style="width:100%;border-collapse:collapse">
          <thead>
            <tr style="text-align:left">
              <th style="padding:8px;border-bottom:1px solid #666">Channel</th>
              <th style="padding:8px;border-bottom:1px solid #666">Title</th>
              <th style="padding:8px;border-bottom:1px solid #666">Video ID</th>
              <th style="padding:8px;border-bottom:1px solid #666">Comment</th>
              <th style="padding:8px;border-bottom:1px solid #666">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows or '<tr><td colspan="5" style="padding:16px;color:#999">No pending items 🎉</td></tr>'}
          </tbody>
        </table>

        <script>
          async function markPinned(videoId) {{
            const res = await fetch('/pin-queue/mark', {{
              method: 'POST',
              headers: {{'Content-Type': 'application/json'}},
              body: JSON.stringify({{ video_id: videoId }})
            }});
            const json = await res.json();
            if (json.ok) location.reload();
            else alert('Could not mark pinned.');
          }}
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)

# ---------- Entrypoint ----------
if __name__ == "__main__":
    def open_browser():
        import time
        time.sleep(1)
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=open_browser, daemon=True).start()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
