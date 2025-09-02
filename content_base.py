import os
import re
import json
import time
import requests
from yt_dlp import YoutubeDL
from youtube_search import YoutubeSearch
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from upload_ec2 import Uploader
from shared_state import get_progress, set_progress
from dotenv import load_dotenv
from yt_video_multi import upload_all_stems
from concurrent.futures import ThreadPoolExecutor

# Keep these EXACT strings consistent across the app (uploader maps, branding_utils, UI)
CHANNEL_NAME_MAP = {
    "son_got_acappellas": "Son Got Acappellas",
    "son_got_drums": "Son Got Drums",
    "main_channel": "Main Channel",
    "sample_split": "Sample Split",
    "sgs_2": "SGS 2",
}

load_dotenv()

class ContentBase:
    def __init__(self, args: dict, track_info: dict = None):
        self.args = args
        self.session_id = args.get("session_id", "default")
        self.track_info = track_info or args.get("track_info")
        self.channel_key = args.get("channel")
        self.channel_label = CHANNEL_NAME_MAP.get(self.channel_key, self.channel_key)
        self.trim_track = args.get("trim_track", False)
        self.trim_length = args.get("trim_length", 72)

        self.universal_id = args.get("universal_id")
        self.stem_base_path = args.get("stem_base_path") or (
            os.path.join("separated", "htdemucs_6s", self.universal_id) if self.universal_id else ""
        )

        # Normalize genre like other classes do
        self.selected_genre = args.get("genre", "Other").strip().title()
        self.video_paths = {}  # e.g. {"acapella": "/path/to/video.mp4", "drums": "/path/to/video.mp4"}

        print(f"\n📥 ContentBase initialized with session_id: {self.session_id}")
        print(f"🔎 Received BPM: {args.get('bpm')} | Key: {args.get('key')}")
        print(f"📦 Track info present: {'Yes' if self.track_info else 'No'}")
        print(f"🎛  Playlist selection: {args.get('playlist_selection', 'none')} | Test mode: {bool(args.get('test_mode', False))}\n")

        self.CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
        self.CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
        self.sp = Spotify(auth_manager=SpotifyClientCredentials(
            client_id=self.CLIENT_ID,
            client_secret=self.CLIENT_SECRET
        ))

    def get_stem_path(self, stem_name: str) -> str:
        return os.path.join(self.stem_base_path, f"{stem_name}.mp3") if self.stem_base_path else ""

    # Make sanitize_name consistent with your stem classes (allow spaces/dashes/brackets/underscores)
    def sanitize_name(self, name: str) -> str:
        return "".join(c for c in name if c.isalnum() or c in " -_[]()").strip()

    def build_meta(self, stem_type: str, channel: str, track: dict) -> dict:
        return {
            "track_id": track.get("id"),
            "stem": stem_type.lower(),
            "channel": channel,
            "artist": track.get("artist"),
            "title": track.get("name"),
            "bpm": int(track.get("tempo", 0)),
            "key": track.get("key"),
        }

    def update_progress(self, message: str, metadata: dict = None, step_percent: float = None):
        current = get_progress(self.session_id)
        meta = current.get("meta", {}) if current else {}
        percent = current.get("percent", 0) if current else 0

        if step_percent is not None:
            percent = max(percent, min(100, step_percent))

        enriched_meta = {
            "stem": meta.get("stem"),
            "channel": meta.get("channel"),
            "artist": meta.get("artist"),
            "track": meta.get("track"),
            "bpm": meta.get("bpm"),
            "key": meta.get("key"),
            "title": meta.get("title"),
            **(metadata or {})
        }

        set_progress(self.session_id, {
            "message": message,
            "percent": percent,
            "meta": enriched_meta
        })
        print(f"[UPDATE] {self.session_id} → {message} ({percent}%)")

    def mark_step_complete(self, message: str, extra_meta: dict = None):
        progress = get_progress(self.session_id)
        if not progress:
            return

        meta = progress.get("meta", {})
        completed = meta.get("completed", 0) + 1
        total = meta.get("total", 1)
        percent = int((completed / total) * 100)

        enriched_meta = {
            "completed": completed,
            "total": total,
            "stem": meta.get("stem"),
            "channel": meta.get("channel"),
            "artist": meta.get("artist"),
            "track": meta.get("track"),
            "bpm": meta.get("bpm"),
            "key": meta.get("key"),
            "title": meta.get("title"),
            **(extra_meta or {})
        }

        set_progress(self.session_id, {
            "message": message,
            "percent": percent,
            "meta": enriched_meta
        })
        print(f"[DONE] {self.session_id}: {percent}% ({completed}/{total}) → {message}")

    def progress_with_meta(self, message: str, step: int, total: int, stem: str, channel: str, track: dict):
        meta = self.build_meta(stem, channel, track)
        self.incremental_progress(message, step, total, meta)

    def fail_progress_with_meta(self, message: str, stem: str, channel: str, track: dict):
        meta = self.build_meta(stem, channel, track)
        self.update_progress(message, meta)

    def mark_complete_with_meta(self, message: str, stem: str, channel: str, track: dict):
        meta = self.build_meta(stem, channel, track)
        self.mark_step_complete(message, meta)

    def upload_batch_to_youtube(self, track):
        """
        Call the uploader ONCE per track with all stems collected in self.video_paths.
        This preserves args (incl. playlist_selection/test_mode) and lets the uploader
        decide playlist auto-add logic.
        """
        try:
            artist = track.get("artist")
            self.update_progress("📤 Uploading stems to YouTube...", {"artist": artist})

            # Single call with the full mapping
            # self.video_paths keys should be normalized like "acapella", "drums", "bass", ...
            payload = {artist: self.video_paths}
            print("🧩 Aggregated upload payload:", json.dumps(payload, indent=2))

            # In test mode, the uploader will print actions instead of calling the API
            upload_all_stems(artist_file_map=payload, args=self.args)

            self.update_progress("✅ Upload step complete", {"artist": artist})
        except Exception as e:
            self.update_progress(f"❌ Batch upload failed: {e}", {"artist": track.get("artist")})

    def upload_to_youtube(self, stem_type, video_path, title, track):
        # Keep for compatibility; most classes directly set self.video_paths themselves
        try:
            if stem_type and video_path:
                self.video_paths[stem_type] = video_path
        except Exception as e:
            self.update_progress(f"❌ Upload tracking failed: {e}", {"stem": stem_type})

    def upload_to_ec2_if_needed(self, local_path):
        if self.args.get("ec2"):
            try:
                self.update_progress("📡 Uploading to EC2...", {"path": local_path})
                uploader = Uploader()
                uploader.upload_to_ec2(local_path)
                self.update_progress("✅ Upload to EC2 complete", {"path": local_path})
            except Exception as e:
                self.update_progress(f"❌ EC2 upload failed: {e}", {"path": local_path})

    def download_audio(self, title, artist):
        search_term = f"{title} - {artist} topic"
        try:
            results = YoutubeSearch(search_term, max_results=1).to_json()
            video_id = json.loads(results)["videos"][0]["id"]
        except Exception as e:
            print("❌ YouTube search failed:", e)
            return None, None

        try:
            os.makedirs("MP3", exist_ok=True)
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": "%(uploader)s - %(id)s.%(ext)s",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192"
                }]
            }

            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_id, download=False)
                uid = f"{info['uploader']} - {info['id']}"
                temp_mp3 = f"{uid}.mp3"
                final_path = f"MP3/{uid}.mp3"

                ydl.download([video_id])

                if os.path.exists(temp_mp3):
                    os.rename(temp_mp3, final_path)
                    return uid, final_path
                else:
                    print(f"❌ MP3 not found after download: {temp_mp3}")
                    return None, None
        except Exception as e:
            print("❌ YouTube download failed:", e)
            return None, None

    def download_thumbnail(self, url, artist=None, title=None, bpm=None, key=None):
        try:
            artist = artist or self.track_info.get("artist", "Unknown")
            title = title or self.track_info.get("name", "Unknown")
            bpm = bpm or self.track_info.get("tempo", 0)
            key = key or self.track_info.get("key", "Unknown")

            folder_title = self.sanitize_name(f"{artist} - {title} [{bpm} BPM_{key}]")
            thumb_dir = os.path.join("Thumbnails", folder_title)
            os.makedirs(thumb_dir, exist_ok=True)

            thumb_path = os.path.join(thumb_dir, "cover.png")

            if os.path.exists(thumb_path):
                return thumb_path

            data = requests.get(url, timeout=15).content
            with open(thumb_path, "wb") as f:
                f.write(data)

            return thumb_path
        except Exception as e:
            print("❌ Thumbnail download failed:", e)
            return None

    def get_track_info(self, track_id):
        if self.track_info:
            print(f"[CACHE] Reusing track info for {self.session_id}")
            return self.track_info

        try:
            track = self.sp.track(track_id)
            artist = track['artists'][0]['name']
            title = track['name']
            album_images = track["album"]["images"]
            img_url = album_images[0]["url"] if album_images else ""

            genre_items = self.sp.search(q=f"artist:{artist}", type="artist").get("artists", {}).get("items", [])
            genre = genre_items[0]["genres"][0] if genre_items and genre_items[0].get("genres") else "Other"

            bpm = self.args.get("bpm") or self.args.get("track_info", {}).get("tempo", 0)
            key = self.args.get("key") or self.args.get("track_info", {}).get("key", "Unknown")

            if not bpm or not key or key == "Unknown":
                try:
                    feat = self.sp.audio_features([track_id])[0]
                    if not bpm:
                        bpm = round(feat.get('tempo', 0))
                    if not key or key == "Unknown":
                        key_index = feat.get('key', 0)
                        key_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
                        key = key_names[key_index] if 0 <= key_index < len(key_names) else key
                except Exception as e:
                    print(f"⚠️ Spotify fallback failed: {e}")

            track_info = {
                "name": title,
                "artist": artist,
                "album": track["album"]["name"],
                "category": [genre.title().replace(" ", "_")],
                "release_date": track["album"]["release_date"],
                "popularity": track["popularity"],
                "img": img_url,
                "tempo": bpm,
                "key": key
            }

            self.track_info = track_info
            print(f"🎯 Final track info: BPM={track_info.get('tempo')} | Key={track_info.get('key')}\n")
            return track_info

        except Exception as e:
            print(f"❌ Track info error: {e}")
            return None

    def trim_audio(self, path: str, duration: int) -> str:
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(path)
            trimmed = audio[:duration * 1000]
            trimmed.export(path, format="mp3")
            return path
        except Exception as e:
            print(f"❌ Failed to trim audio: {e}")
            return path

    def stems_already_exist(self):
        if not self.stem_base_path:
            return False
        try:
            files = os.listdir(self.stem_base_path)
            return len([f for f in files if f.endswith(".mp3")]) >= 4
        except Exception:
            return False
