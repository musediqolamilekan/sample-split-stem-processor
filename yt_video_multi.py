# yt_video_multi.py
import os
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import pytz
import json
from pathlib import Path

YT_TOKEN_DIR = "yt_tokens"
PIN_QUEUE_FILE = "pin_queue.jsonl"   # local tracker for manual pinning

CHANNEL_KEY_TO_NAME = {
    "son_got_acapellas": "Son Got Acapellas",
    "son_got_drums": "Son Got Drums",
    "main_channel": "Main Channel",
    "sgs_2": "SGS 2",
    "sample_split": "Sample Split",
}

def normalize_stem(stem: str) -> str:
    s = (stem or "").strip().lower()
    if s == "vocals":
        return "acapella"
    return s

UPLOAD_MAP = {
    "acapella": [
        {"channel": "Son Got Acapellas", "token": "abc_vocal.json"},
        {"channel": "Main Channel", "token": "abc_main.json"},
        {"channel": "Sample Split", "token": "abc_split.json"},
        {"channel": "SGS 2", "token": "abc_backup.json"},
    ],
    "drums": [
        {"channel": "Son Got Drums", "token": "abc_drums.json"},
        {"channel": "Main Channel", "token": "abc_main.json"},
        {"channel": "Sample Split", "token": "abc_split.json"},
        {"channel": "SGS 2", "token": "abc_backup.json"},
    ],
    "bass": [
        {"channel": "Sample Split", "token": "abc_split.json"},
    ],
    "instrumental": [
        {"channel": "Sample Split", "token": "abc_split.json"},
    ],
    "melody": [
        {"channel": "Sample Split", "token": "abc_split.json"},
    ],
}

STEM_ORDER = {
    "Son Got Acapellas": ["acapella"],
    "Son Got Drums": ["drums"],
    "Main Channel": ["acapella", "drums"],
    "SGS 2": ["acapella", "drums"],
    "Sample Split": ["acapella", "drums", "bass", "instrumental", "melody"],
}

# 🔗 Replace with your real playlist IDs (optional, kept from earlier step)
PLAYLIST_IDS = {
    "Son Got Acapellas": {"acapella": "PL_REPLACE_ME_ACAPELLA_SGA", "drumz": "PL_REPLACE_ME_DRUMZ_SGA"},
    "Son Got Drums": {"drumz": "PL_REPLACE_ME_DRUMZ_SGD", "acapella": "PL_REPLACE_ME_ACAPELLA_SGD"},
    "Main Channel": {"acapella": "PL_REPLACE_ME_ACAPELLA_MAIN", "drumz": "PL_REPLACE_ME_DRUMZ_MAIN"},
    "SGS 2": {"acapella": "PL_REPLACE_ME_ACAPELLA_SGS2", "drumz": "PL_REPLACE_ME_DRUMZ_SGS2"},
    "Sample Split": {"acapella": "PL_REPLACE_ME_ACAPELLA_SPLIT", "drumz": "PL_REPLACE_ME_DRUMZ_SPLIT"},
}

# ---------- NEW: Templated pinned comments ----------
COMMENT_TEMPLATES = {
    # channel-specific if you want
    "Son Got Acapellas": "🔥 Enjoy the {stem_title}? Subscribe & get daily stems.\n#stems #acapella #remix",
    "Son Got Drums": "🥁 Drum-only version! Drop your flips & subscribe for more.\n#stems #drums #producers",
    "Main Channel": "🎧 New {stem_title} just dropped. Like, comment your flip, and subscribe!\n#stems",
    "SGS 2": "🚀 Backup drop: {stem_title}. Turn on notifications for daily uploads.\n#stems",
    "Sample Split": "🧩 {stem_title} from Sample Split. More in the playlists — subscribe!\n#samplesplit",
}
DEFAULT_COMMENT = "🔥 Thanks for listening! More daily stems — subscribe & check the playlists.\n#stems"

def _stem_title(artist, track_title, stem, bpm, key):
    if stem == "drums":
        return f"{artist} - {track_title} Drums [{bpm} BPM]"
    return f"{artist} - {track_title} {stem.capitalize()} [{bpm} BPM_{key}]"

def get_youtube_client(token_path: str):
    try:
        credentials = Credentials.from_authorized_user_file(
            token_path,
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.force-ssl",  # needed for comments
            ],
        )
        return build("youtube", "v3", credentials=credentials)
    except Exception as e:
        print(f"❌ Failed to initialize YouTube client with token {token_path}: {e}")
        return None

def _build_title(artist: str, track_title: str, stem: str, bpm, key):
    stem_cap = stem.capitalize()
    try:
        bpm_int = int(bpm) if bpm is not None else 0
    except Exception:
        bpm_int = bpm
    if stem == "drums":
        return f"{artist} - {track_title} {stem_cap} [{bpm_int} BPM]"
    return f"{artist} - {track_title} {stem_cap} [{bpm_int} BPM_{key}]"

# ---------- NEW: comment posting + queue helpers ----------
def _append_pin_queue(item: dict):
    Path(PIN_QUEUE_FILE).touch(exist_ok=True)
    with open(PIN_QUEUE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

def _queue_for_pinning(channel: str, video_id: str, title: str, comment_text: str):
    _append_pin_queue({
        "video_id": video_id,
        "channel": channel,
        "title": title,
        "comment": comment_text,
        "pinned": False,
        "created_at": datetime.utcnow().isoformat() + "Z",
    })

def _post_top_level_comment(youtube, video_id: str, text: str):
    """Real API call (safe to skip in print/dry mode)."""
    try:
        body = {
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {
                        "textOriginal": text
                    }
                }
            }
        }
        return youtube.commentThreads().insert(part="snippet", body=body).execute()
    except Exception as e:
        print(f"⚠️ Failed to post comment on {video_id}: {e}")
        return None

def upload_video(youtube, file_path, artist, stem_type, channel, **kwargs):
    """Print-only stub; returns TEST_ID."""
    try:
        title = kwargs.get("title", f"{artist} - {stem_type.capitalize()}")
        description = kwargs.get("description", "")
        tags = kwargs.get("tags", [])
        publish_at = kwargs.get("publish_at")
        made_for_kids = kwargs.get("made_for_kids", False)
        privacy_status = kwargs.get("privacy_status", "private")
        category_id = kwargs.get("category_id", "10")

        payload = {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
            "privacyStatus": privacy_status,
            "madeForKids": made_for_kids,
            "publishAt": publish_at,
            "file_path": file_path,
            "channel": channel,
        }
        print(f"📦 Would upload to YouTube: {payload}")
        return {"id": "TEST_ID"}  # when you switch to real upload, this will be the real videoId
    except Exception as e:
        print(f"❌ YouTube upload (print mode) failed for {artist} - {stem_type} → {channel}: {e}")
        return None

def upload_all_stems(artist_file_map: dict, args: dict):
    print("📥 Input artist_file_map:", artist_file_map)
    print("⚙️ Input args:", args)

    raw_channels = args.get("channels") or ([args.get("channel")] if args.get("channel") else [])
    channels = [CHANNEL_KEY_TO_NAME.get(c, c) for c in raw_channels]

    # normalize stems in map
    normalized_artist_file_map = {}
    for artist, file_paths in (artist_file_map or {}).items():
        normalized_artist_file_map[artist] = {normalize_stem(k): v for k, v in (file_paths or {}).items()}
    artist_file_map = normalized_artist_file_map

    schedule_start = args.get("schedule_start_time")
    timezone_str = args.get("timezone", "America/Chicago")
    interval_minutes = args.get("schedule_interval_minutes", 0)
    default_description = args.get("description", "")
    tags = args.get("tags", [])
    is_for_kids = args.get("made_for_kids", False)
    monetize = args.get("monetize", False)
    privacy_status = args.get("privacy", "private")
    playlist_selection = (args.get("playlist_selection") or "none").strip().lower()
    auto_comment = args.get("auto_comment", True)  # NEW: allow disabling if needed

    all_uploads = []
    seen = set()

    print("\n🔄 Organizing uploads per channel...")
    for artist, file_paths in artist_file_map.items():
        for channel_name in channels:
            stem_types = STEM_ORDER.get(channel_name, [])
            for stem_type in stem_types:
                fp = file_paths.get(stem_type)
                if not fp:
                    continue

                valid_channels = [entry["channel"] for entry in UPLOAD_MAP.get(stem_type, [])]
                if channel_name not in valid_channels:
                    print(f"⚠️ Skipping invalid combination: {channel_name} ← {stem_type}")
                    continue

                tup = (artist, stem_type, channel_name)
                if tup in seen:
                    continue
                seen.add(tup)

                token = next((e["token"] for e in UPLOAD_MAP[stem_type] if e["channel"] == channel_name), None)
                if not token:
                    print(f"⚠️ No token found for {channel_name} → {stem_type}")
                    continue

                all_uploads.append({
                    "artist": artist,
                    "stem": stem_type,          # "acapella" | "drums" | ...
                    "channel": channel_name,    # pretty name
                    "file_path": fp,
                    "token": token
                })

    print(f"\n📦 Total uploads queued: {len(all_uploads)}")

    # schedule times (optional)
    artist_to_index = {artist: args.get("global_artist_index", 0) for artist in artist_file_map.keys()}
    artist_publish_times = {}
    if schedule_start:
        try:
            local_tz = pytz.timezone(timezone_str)
            base_dt = local_tz.localize(datetime.strptime(schedule_start, "%Y-%m-%dT%H:%M"))
            for artist, index in artist_to_index.items():
                offset_dt = base_dt + timedelta(minutes=index * interval_minutes)
                offset_utc = offset_dt.astimezone(pytz.utc)
                publish_at = offset_utc.isoformat().replace("+00:00", "Z")
                artist_publish_times[artist] = publish_at
                print(f"⏰ Artist '{artist}' → {offset_dt} local → {publish_at} UTC")
        except Exception as e:
            print(f"⚠️ Scheduling error: {e}")

    for item in all_uploads:
        track_info = args.get("track_info", {}) or {}
        bpm = args.get("bpm", track_info.get("tempo", ""))
        key = args.get("key", track_info.get("key", ""))
        track_title = track_info.get("name", "Unknown Title")

        yt_title = _build_title(item["artist"], track_title, item["stem"], bpm, key)
        publish_at = artist_publish_times.get(item["artist"])

        print("📦 YouTube upload payload:")
        print({
            "title": yt_title,
            "description": default_description,
            "tags": tags,
            "categoryId": "10",
            "privacyStatus": privacy_status,
            "madeForKids": is_for_kids,
            "publishAt": publish_at,
            "monetize": monetize,
            "file_path": item["file_path"],
            "channel": item["channel"],
            "token": item["token"]
        })

        token_path = os.path.join(YT_TOKEN_DIR, item["token"])
        youtube = get_youtube_client(token_path)  # may be None if token bad

        # Print-only "upload"
        result = upload_video(
            youtube=youtube,
            file_path=item["file_path"],
            artist=item["artist"],
            stem_type=item["stem"],
            channel=item["channel"],
            title=yt_title,
            description=default_description,
            tags=tags,
            category_id="10",
            privacy_status=privacy_status,
            made_for_kids=is_for_kids,
            publish_at=publish_at,
            monetize=monetize
        )

        video_id = (result or {}).get("id")

        # ---------- NEW: Auto top-level comment + queue for manual pinning ----------
        if auto_comment:
            stem_title = _stem_title(item["artist"], track_title, item["stem"], bpm, key)
            comment_template = COMMENT_TEMPLATES.get(item["channel"], DEFAULT_COMMENT)
            comment_text = comment_template.format(stem_title=stem_title)

            if video_id and not str(video_id).startswith("TEST_") and youtube:
                api_resp = _post_top_level_comment(youtube, video_id, comment_text)
                if api_resp:
                    print(f"📝 Posted comment on {video_id} for channel {item['channel']}")
                else:
                    print(f"📝 Would post comment on {video_id}: {comment_text}")
            else:
                print(f"📝 [TEST MODE] Would post comment: {comment_text}")

            # Always queue so you can pin manually in Studio
            _queue_for_pinning(item["channel"], video_id or "TEST_ID", yt_title, comment_text)

        # ---------- (Optional) Playlist auto-add printout kept from earlier ----------
        do_acapella = playlist_selection == "acapella" and item["stem"] == "acapella"
        do_drumz = playlist_selection == "drumz" and item["stem"] == "drums"
        if video_id and (do_acapella or do_drumz):
            pl_key = "acapella" if do_acapella else "drumz"
            playlist_id = (PLAYLIST_IDS.get(item["channel"], {}) or {}).get(pl_key)
            if playlist_id:
                print(f"📋 Would add video {video_id} to playlist {playlist_id} ({pl_key}) on channel {item['channel']}")
            else:
                print(f"ℹ️ No playlist configured for channel '{item['channel']}' and selection '{pl_key}'.")
        else:
            if playlist_selection == "none":
                print("ℹ️ Playlist selection is 'none' — skipping playlist add.")
            else:
                print(f"ℹ️ Playlist '{playlist_selection}' selected but stem '{item['stem']}' does not match; skipping.")
