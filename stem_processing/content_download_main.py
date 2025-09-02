import os, time, shutil
from moviepy.editor import ImageClip, AudioFileClip
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, COMM
from content_base import ContentBase
from shared_state import get_progress, set_progress
from branding_utils import add_intro_card

if "comment" not in EasyID3.valid_keys:
    EasyID3.RegisterTXXXKey("comment", "comment")

class Content_download_main(ContentBase):
    """
    Main channel publishes Acapella + Drums.
    - Inputs: stem_base_path/vocals.mp3 (→ label: Acapella), stem_base_path/drums.mp3 (→ label: Drums)
    - Folder org (#4): <Channel>/<Genre>/<StemType>/<Artist - Title ...>
    - Naming (#5): Drums = [BPM]; Acapella = [BPM_Key]
    """

    STEM_SOURCES = [
        ("Acapella", "vocals.mp3", "acapella"),  # (visible label, filename, uploader key)
        ("Drums",    "drums.mp3",  "drums"),
    ]

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

    def sanitize_name(self, name):
        return "".join(c for c in name if c.isalnum() or c in " -_[]() ").strip()

    def _build_folder_title(self, artist, title, stem_label, bpm, key):
        """Title rules per #5."""
        if stem_label.lower() == "drums":
            return self.sanitize_name(f"{artist} - {title} {stem_label} [{bpm} BPM]")
        return self.sanitize_name(f"{artist} - {title} {stem_label} [{bpm} BPM_{key}]")

    def tag_stem(self, file_path, stem_label, bpm, key):
        """Drums: BPM only; others: BPM + Key."""
        try:
            audio = EasyID3(file_path)
            audio["title"] = f"{stem_label} stem"
            if stem_label.lower() == "drums":
                audio["comment"] = f"BPM: {bpm}"
            else:
                audio["comment"] = f"Key: {key}, BPM: {bpm}"
            audio.save()
        except Exception:
            audio = MP3(file_path, ID3=ID3)
            if audio.tags is None:
                audio.add_tags()
            audio.tags.add(TIT2(encoding=3, text=f"{stem_label} stem"))
            comment_text = f"BPM: {bpm}" if stem_label.lower() == "drums" else f"Key: {key}, BPM: {bpm}"
            audio.tags.add(COMM(encoding=3, lang='eng', desc='desc', text=comment_text))
            audio.save()

    def render_video(self, file_path, thumb_path, stem_label, channel, artist, track_title, bpm, key):
        """
        MP4 path per #4: MP4/<channel>/<genre>/<StemType>/<Artist - Title ...>.mp4
        Naming per #5.
        """
        try:
            genre = self.selected_genre
            folder_title = self._build_folder_title(artist, track_title, stem_label, bpm, key)
            filename = f"{folder_title}.mp4"
            out_dir = os.path.join("MP4", channel, genre, stem_label, folder_title)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, filename)

            audio = AudioFileClip(file_path)
            branded_clip = add_intro_card(audio.duration, channel, thumb_path, stem_label)
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
            print(f"❌ Error rendering video: {e}")
            return None

    def wait_for_stem(self, stem_path):
        wait_time = 0
        while not os.path.exists(stem_path) and wait_time < 20:
            time.sleep(1)
            wait_time += 1
        return os.path.exists(stem_path)

    def download(self, track_id):
        total_steps = 6
        channel = self.channel_label
        track = self.track_info

        if not track:
            self.fail_progress_with_meta("❌ track_info missing", "main", channel, {"id": track_id})
            return

        bpm = int(track["tempo"])
        key = track["key"]
        artist = track["artist"]
        title = track["name"]

        self.video_paths = {}
        self.progress_with_meta("🔍 Using shared metadata...", 1, total_steps, "main", channel, track)

        if not self.stem_base_path or not os.path.exists(self.stem_base_path):
            self.fail_progress_with_meta("❌ stem_base_path missing or invalid", "main", channel, track)
            return

        self.progress_with_meta("🖼️ Downloading thumbnail...", 2, total_steps, "main", channel, track)
        thumb_path = self.download_thumbnail(track["img"], artist=artist, title=title, bpm=bpm, key=key)

        # Process Acapella and Drums in order
        for i, (visible_label, filename, uploader_key) in enumerate(self.STEM_SOURCES):
            stem_file = os.path.join(self.stem_base_path, filename)
            if not self.wait_for_stem(stem_file):
                self.update_progress(f"❌ {visible_label} stem not found", {"stem": visible_label})
                continue

            folder_title = self._build_folder_title(artist, title, visible_label, bpm, key)
            # ✅ Folder org (#4): <channel>/<genre>/<StemType>/<Artist - Title ...>
            out_dir = os.path.join(channel, self.selected_genre, visible_label, folder_title)
            os.makedirs(out_dir, exist_ok=True)

            final_name = f"{folder_title}.mp3"
            final_path = os.path.join(out_dir, final_name)
            shutil.copy(stem_file, final_path)

            if self.trim_track:
                final_path = self.trim_audio(final_path, self.trim_length)

            meta = self.build_meta(visible_label, channel, track)
            self.incremental_progress(f"🏷️ Tagging {visible_label}...", 3 + i * 0.5, total_steps, meta)
            self.tag_stem(final_path, visible_label, bpm, key)

            self.incremental_progress(f"🎬 Rendering {visible_label} video...", 3.2 + i * 0.5, total_steps, meta)
            video_path = self.render_video(final_path, thumb_path, visible_label, channel, artist, title, bpm, key)
            if video_path:
                # ✅ Use uploader keys "acapella" / "drums"
                self.video_paths[uploader_key] = video_path

            self.progress_with_meta(f"⏫ Uploading {visible_label} to EC2...", 3.6 + i * 0.5, total_steps, visible_label, channel, track)
            self.upload_to_ec2_if_needed(out_dir)

        if self.args.get("yt") and self.video_paths:
            self.upload_batch_to_youtube(track)
        else:
            self.update_progress("⏭️ YouTube upload skipped", {"yt_enabled": self.args.get("yt", False)})

        self.mark_complete_with_meta("✅ Main processing complete", "main", channel, track)
