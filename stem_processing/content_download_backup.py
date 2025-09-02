import os, time, shutil
from moviepy.editor import ImageClip, AudioFileClip
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, COMM
import requests
from content_base import ContentBase
from shared_state import get_progress, set_progress
from branding_utils import add_intro_card

if "comment" not in EasyID3.valid_keys:
    EasyID3.RegisterTXXXKey("comment", "comment")

class Content_download_backup(ContentBase):
    """
    Backup (SGS 2) now publishes: Acapella + Drums.
    - Sources:
        Acapella  -> stem_base_path/vocals.mp3
        Drums     -> stem_base_path/drums.mp3
    - Folder org (#4): <channel>/<genre>/<StemType>/<Artist - Title ...>
    - Naming (#5): Drums = [BPM]; Acapella = [BPM_Key]
    """

    STEM_SOURCES = {
        "Acapella": "vocals.mp3",
        "Drums": "drums.mp3",
    }

    def __init__(self, args: dict):
        super().__init__(args)
        self.track_info = args.get("track_info", {})
        self.stem_base_path = args.get("stem_base_path", "")
        self.selected_genre = args.get("genre", "Other")
        self.video_paths = {}
        self.trim_track = args.get("trim_track", False)
        self.trim_length = args.get("trim_length", 60)
        self.yt = args.get("yt", False)

    def incremental_progress(self, message, step_index, total_steps, metadata=None):
        progress_data = get_progress(self.session_id)
        meta = progress_data.get("meta", {})
        completed = meta.get("completed", 0)
        total = meta.get("total", 1)
        base = (completed / total) * 100 if total else 0
        step_size = 100 / total / total_steps if total_steps else 0
        step_percent = base + step_index * step_size
        updated_progress = {
            "message": message,
            "percent": min(100, round(step_percent, 2)),
            "meta": {**meta, **(metadata or {})}
        }
        set_progress(self.session_id, updated_progress)
        print(f"[PROGRESS] {self.session_id} → {message} ({updated_progress['percent']}%)")

    def tag_stem(self, file_path, stem_type, bpm, key):
        """Drums: BPM only. Others: BPM + Key."""
        try:
            audio = EasyID3(file_path)
            audio["title"] = f"{stem_type} stem"
            if stem_type.lower() == "drums":
                audio["comment"] = f"BPM: {bpm}"
            else:
                audio["comment"] = f"Key: {key}, BPM: {bpm}"
            audio.save()
        except Exception:
            audio = MP3(file_path, ID3=ID3)
            if audio.tags is None:
                audio.add_tags()
            audio.tags.add(TIT2(encoding=3, text=f"{stem_type} stem"))
            comment_text = f"BPM: {bpm}" if stem_type.lower() == "drums" else f"Key: {key}, BPM: {bpm}"
            audio.tags.add(COMM(encoding=3, lang='eng', desc='desc', text=comment_text))
            audio.save()

    def _build_folder_title(self, artist, title, stem_type, bpm, key):
        """Naming rule helper."""
        if stem_type.lower() == "drums":
            return self.sanitize_name(f"{artist} - {title} {stem_type} [{bpm} BPM]")
        return self.sanitize_name(f"{artist} - {title} {stem_type} [{bpm} BPM_{key}]")

    def render_video(self, file_path, thumb_path, stem_type, channel, artist, track_title, bpm, key):
        """
        MP4 path per #4: MP4/<channel>/<genre>/<StemType>/<Artist - Title ...>.mp4
        Uses naming per #5 (Drums = BPM; others = BPM+Key)
        """
        try:
            genre = self.selected_genre
            folder_title = self._build_folder_title(artist, track_title, stem_type, bpm, key)
            filename = f"{folder_title}.mp4"
            out_dir = os.path.join("MP4", channel, genre, stem_type, folder_title)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, filename)

            audio = AudioFileClip(file_path)
            branded_clip = add_intro_card(audio.duration, channel, thumb_path, stem_type)
            if not branded_clip:
                branded_clip = (
                    ImageClip(thumb_path)
                    .resize((720, 720))
                    .on_color(size=(1280, 720), color=(0, 0, 0), pos="center")
                    .set_duration(audio.duration)
                )

            final_video = branded_clip.set_audio(audio)
            final_video.write_videofile(out_path, fps=1, codec="libx264", audio_codec="aac")
            return out_path
        except Exception as e:
            print(f"❌ Failed to render video: {e}")
            return None

    def sanitize_name(self, name):
        return "".join(c for c in name if c.isalnum() or c in " -_[]()").strip()

    def wait_for_stem(self, stem_path, stem_type):
        waited = 0
        while not os.path.exists(stem_path) and waited < 20:
            time.sleep(1)
            waited += 1
        if not os.path.exists(stem_path):
            print(f"❌ {stem_type} stem missing after wait at {stem_path}")
            return False
        return True

    def download_thumbnail(self, img_url, artist, title, bpm, key):
        # Keep thumbnail path consistent with your other classes (no stem layer here).
        folder_title = self.sanitize_name(f"{artist} - {title} [{bpm} BPM_{key}]")
        thumb_folder = os.path.join("Thumbnails", folder_title)
        os.makedirs(thumb_folder, exist_ok=True)
        thumb_path = os.path.join(thumb_folder, "cover.png")
        if not os.path.exists(thumb_path):
            try:
                data = requests.get(img_url, timeout=15).content
                with open(thumb_path, "wb") as f:
                    f.write(data)
            except Exception as e:
                print(f"⚠️ Thumbnail download failed: {e}")
        return thumb_path if os.path.exists(thumb_path) else None

    def process_single_stem(self, stem_type: str, src_file: str, channel: str, track: dict, total_steps: int):
        """Process one stem (Acapella or Drums) end-to-end for SGS 2."""
        bpm = int(track["tempo"])
        key = track["key"]
        artist = track["artist"]
        title = track["name"]

        meta = self.build_meta(stem_type, channel, track)
        self.incremental_progress("🖼️ Downloading thumbnail...", 2, total_steps, meta)
        thumb_path = self.download_thumbnail(track["img"], artist, title, bpm, key)

        # ✅ Folder org (#4) + Naming (#5)
        folder_title = self._build_folder_title(artist, title, stem_type, bpm, key)
        base_folder = os.path.join(channel, self.selected_genre, stem_type, folder_title)
        os.makedirs(base_folder, exist_ok=True)

        src_path = os.path.join(self.stem_base_path, src_file)
        if not self.wait_for_stem(src_path, stem_type):
            self.update_progress(f"❌ {stem_type} stem not found", meta)
            return

        final_path = os.path.join(base_folder, f"{folder_title}.mp3")
        shutil.copy(src_path, final_path)

        if self.trim_track:
            final_path = self.trim_audio(final_path, self.trim_length)

        self.incremental_progress(f"🏷️ Tagging {stem_type} MP3...", 3, total_steps, meta)
        self.tag_stem(final_path, stem_type, bpm, key)

        self.incremental_progress(f"🎬 Rendering {stem_type} video...", 3.5, total_steps, meta)
        video_path = self.render_video(final_path, thumb_path, stem_type, channel, artist, title, bpm, key)
        if video_path:
            key_name = "acapella" if stem_type.lower() == "acapella" else "drums"
            self.video_paths[key_name] = video_path

        self.upload_to_ec2_if_needed(base_folder)

    def download(self, track_id):
        total_steps = 4
        channel = self.channel_label
        self.video_paths = {}

        try:
            track = self.track_info
            if not track:
                self.fail_progress_with_meta("❌ Missing track_info", "acapella", channel, {"id": track_id})
                return

            # Step 1: basic validation
            self.progress_with_meta("🔍 Using shared metadata...", 1, total_steps, "acapella", channel, track)
            if not self.stem_base_path or not os.path.exists(self.stem_base_path):
                self.fail_progress_with_meta("❌ Invalid or missing stem_base_path", "acapella", channel, track)
                return

            # Process Acapella then Drums
            for label, filename in self.STEM_SOURCES.items():
                self.process_single_stem(label, filename, channel, track, total_steps)

            # YouTube (batch) – relies on self.video_paths["acapella"] and ["drums"]
            if self.yt and self.video_paths:
                self.upload_batch_to_youtube(track)
            else:
                self.update_progress("⏭️ YouTube upload skipped", {"yt_enabled": self.yt})

            self.progress_with_meta("✅ SGS 2 (Backup) processing complete", 4, total_steps, "acapella", channel, track)
            self.mark_complete_with_meta("✅ SGS 2 (Backup) complete", "acapella", channel, track)

        except Exception as e:
            self.fail_progress_with_meta(f"❌ Backup error for {track_id}: {e}", "acapella", channel, {"id": track_id})
