import os, subprocess, time, shutil
from moviepy.editor import ImageClip, AudioFileClip
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, COMM
from content_base import ContentBase
from shared_state import get_progress, set_progress
from branding_utils import add_intro_card

if "comment" not in EasyID3.valid_keys:
    EasyID3.RegisterTXXXKey("comment", "comment")

class Content_download_split(ContentBase):
    """
    Sample Split: produce Bass and Melody (melody = Demucs 'other.mp3' i.e., no bass/drums/vocals).
    Folder rule (#4): put each stem under a subfolder named by stem type.
    Naming rule (#5): Drums → [BPM], others → [BPM_Key] (applies to Bass & Melody here).
    """
    STEM_SOURCES = {
        "Bass": "bass.mp3",
        "Melody": "other.mp3",   # <-- melody without bass/drums/vocals straight from Demucs
    }

    def __init__(self, args: dict):
        super().__init__(args)
        self.track_info = args.get("track_info", {})
        self.stem_base_path = args.get("stem_base_path", "")
        self.selected_genre = args.get("genre", "Other")
        self.video_paths = {}
        self.trim_track = args.get("trim_track", False)
        self.trim_length = args.get("trim_length", 60)

    def incremental_progress(self, message, step_index, total_steps, metadata=None):
        progress_data = get_progress(self.session_id)
        meta = progress_data.get("meta", {}) if progress_data else {}
        completed = meta.get("completed", 0)
        total = meta.get("total", 1)
        base = (completed / total) * 100 if total and total_steps else 0
        step_size = 100 / total / total_steps if total and total_steps else 0
        step_percent = base + step_index * step_size
        updated_progress = {
            "message": message,
            "percent": min(100, round(step_percent, 2)),
            "meta": {**meta, **(metadata or {})}
        }
        set_progress(self.session_id, updated_progress)
        print(f"[PROGRESS] {self.session_id} → {message} ({updated_progress['percent']}%)")

    def sanitize_name(self, text):
        return "".join(c for c in text if c.isalnum() or c in " -_[]()").strip()

    def _build_folder_title(self, artist, title, stem_type, bpm, key):
        """#5: Drums = BPM only; others = BPM + Key. (Here: Bass & Melody use BPM+Key)"""
        if stem_type.lower() == "drums":
            return self.sanitize_name(f"{artist} - {title} {stem_type} [{bpm} BPM]")
        return self.sanitize_name(f"{artist} - {title} {stem_type} [{bpm} BPM_{key}]")

    def tag_stem(self, file_path, stem_type, bpm, key):
        try:
            audio = EasyID3(file_path)
            audio["title"] = f"{stem_type} stem"
            # Drums would be BPM-only, but we don't do drums here.
            audio["comment"] = f"Key: {key}, BPM: {bpm}"
            audio.save()
        except Exception:
            audio = MP3(file_path, ID3=ID3)
            if audio.tags is None:
                audio.add_tags()
            audio.tags.add(TIT2(encoding=3, text=f"{stem_type} stem"))
            audio.tags.add(COMM(encoding=3, lang='eng', desc='desc', text=f"Key: {key}, BPM: {bpm}"))
            audio.save()

    def render_video(self, file_path, thumb_path, stem_type, bpm, key, artist, track_title):
        try:
            channel = self.channel_label
            genre = self.selected_genre

            # #5 naming + #4 stem subfolder
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

    def extract_and_upload(self, stem_type, src_path, track, thumb_path, step_index, total_steps):
        bpm = int(track["tempo"])
        key = track["key"]
        artist = track["artist"]
        title = track["name"]
        channel = self.channel_label
        genre = self.selected_genre

        meta = self.build_meta(stem_type, channel, track)

        # #5 naming + #4 stem subfolder
        folder_title = self._build_folder_title(artist, title, stem_type, bpm, key)
        filename = f"{folder_title}.mp3"
        out_dir = os.path.join(channel, genre, stem_type, folder_title)
        os.makedirs(out_dir, exist_ok=True)

        final_path = os.path.join(out_dir, filename)
        shutil.copyfile(src_path, final_path)

        if self.trim_track:
            final_path = self.trim_audio(final_path, self.trim_length)

        self.incremental_progress(f"🏷️ Tagging {stem_type}...", step_index + 0.1, total_steps, meta)
        self.tag_stem(final_path, stem_type, bpm, key)

        self.incremental_progress(f"🎬 Rendering {stem_type} video...", step_index + 0.2, total_steps, meta)
        video_path = self.render_video(final_path, thumb_path, stem_type, bpm, key, artist, title)
        if video_path:
            self.video_paths[stem_type.lower()] = video_path  # "bass", "melody"

        self.progress_with_meta(f"⏫ Uploading {stem_type} to EC2...", step_index + 0.4, total_steps, stem_type, channel, track)
        self.upload_to_ec2_if_needed(out_dir)

    def upload_batch_to_youtube(self, track):
        if self.args.get("yt") and self.video_paths:
            artist = track["artist"]
            args = {**self.args, "channel": self.channel_key}
            self.update_progress("📤 Uploading Sample Split stems (Bass & Melody)...", {"artist": artist})
            from yt_video_multi import upload_all_stems
            upload_all_stems(artist_file_map={artist: self.video_paths}, args=args)

    def download(self, track_id):
        total_steps = 5
        channel = self.channel_label
        track = self.track_info

        if not track:
            self.fail_progress_with_meta("❌ track_info missing", "Melody", channel, {"id": track_id})
            return

        bpm = int(track["tempo"])
        key = track["key"]
        artist = track["artist"]
        title = track["name"]

        self.progress_with_meta("🔍 Using shared metadata...", 1, total_steps, "Melody", channel, track)

        uid = self.args.get("universal_id")
        base_dir = self.stem_base_path
        thumb_path = self.download_thumbnail(track["img"], artist=artist, title=title, bpm=bpm, key=key)

        # Fallback attempt (rarely needed)
        if not os.path.exists(os.path.join(base_dir, "bass.mp3")) and not os.path.exists(os.path.join(base_dir, "other.mp3")):
            sanitized_dir = self.sanitize_name(f"{artist} - {title}")
            base_dir = os.path.join(self.stem_base_path, "separated", "htdemucs_6s", sanitized_dir)

        if not uid or not base_dir or not os.path.exists(base_dir):
            self.fail_progress_with_meta("❌ stem_base_path missing", "Melody", channel, track)
            return

        # Process both stems if present
        processed_any = False
        for stem_label, filename in self.STEM_SOURCES.items():
            src = os.path.join(base_dir, filename)
            if os.path.exists(src):
                step_index = 2 if stem_label == "Bass" else 3
                self.extract_and_upload(stem_label, src, track, thumb_path, step_index, total_steps)
                processed_any = True
            else:
                self.update_progress(f"ℹ️ {stem_label} stem not found ({src})", {"stem": stem_label})

        if not processed_any:
            self.fail_progress_with_meta("❌ No valid stems (Bass/Melody) found", "Melody", channel, track)
            return

        if self.args.get("yt"):
            self.upload_batch_to_youtube(track)
        else:
            self.update_progress("⏭️ YouTube upload skipped", {"yt_enabled": self.args.get("yt", False)})

        self.progress_with_meta("✅ Sample Split (Bass + Melody) complete!", total_steps, total_steps, "Melody", channel, track)
        self.mark_complete_with_meta("✅ Sample Split complete!", "Melody", channel, track)
