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

class Content_download_drum(ContentBase):
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

    def tag_stem(self, file_path, stem_type, bpm, key):
        """For Drums, store BPM only (no key) in the comment."""
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

    def render_video(self, file_path, thumb_path, stem_type, channel, artist, track_title, bpm, key):
        """Drums video path: MP4/<channel>/<genre>/Drums/<Artist - Title Drums [BPM]>.mp4"""
        try:
            genre = self.selected_genre
            # ✅ Drums: BPM only in name
            folder_title = self.sanitize_name(f"{artist} - {track_title} {stem_type} [{bpm} BPM]")
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
            print(f"❌ Error rendering video: {e}")
            return None

    def sanitize_name(self, name):
        return "".join(c for c in name if c.isalnum() or c in " -_[](){}").strip()

    def download(self, track_id):
        total_steps = 7
        channel = self.channel_label
        stem_type = "Drums"

        track = self.track_info
        if not track:
            self.fail_progress_with_meta("❌ track_info unavailable", stem_type, channel, {"id": track_id})
            return

        meta = self.build_meta(stem_type, channel, track)
        self.progress_with_meta("🔍 Preparing drum stem...", 1, total_steps, stem_type, channel, track)

        mp3_path = self.args.get("mp3_path")
        if not mp3_path or not os.path.exists(mp3_path):
            self.fail_progress_with_meta("❌ Shared audio path missing", stem_type, channel, track)
            return

        bpm = int(track["tempo"])
        key = track["key"]
        artist = track["artist"]
        title = track["name"]

        self.progress_with_meta("🖼️ Downloading thumbnail...", 2, total_steps, stem_type, channel, track)
        thumb_path = self.download_thumbnail(track["img"], artist=artist, title=title, bpm=bpm, key=key)

        # ✅ Folder org: <channel>/<genre>/<StemType>/<Artist - Title Drums [BPM]>
        folder_title = self.sanitize_name(f"{artist} - {title} {stem_type} [{bpm} BPM]")
        base_folder = os.path.join(channel, self.selected_genre, stem_type, folder_title)
        os.makedirs(base_folder, exist_ok=True)

        stem_path = os.path.join(self.stem_base_path, "drums.mp3")
        for _ in range(10):
            if os.path.exists(stem_path):
                break
            time.sleep(1)
        else:
            self.fail_progress_with_meta("❌ Drums stem not found after waiting.", stem_type, channel, track)
            return

        # ✅ File name: BPM only for Drums
        final_name = self.sanitize_name(f"{artist} - {title} {stem_type} [{bpm} BPM]")
        final_path = os.path.join(base_folder, f"{final_name}.mp3")
        shutil.copy(stem_path, final_path)

        if self.trim_track:
            final_path = self.trim_audio(final_path, self.trim_length)

        self.incremental_progress("🏷️ Tagging...", 3, total_steps, meta)
        self.tag_stem(final_path, stem_type, bpm, key)

        self.incremental_progress("🎬 Rendering video...", 4, total_steps, meta)
        video_path = self.render_video(final_path, thumb_path, stem_type, channel, artist, title, bpm, key)
        if video_path:
            self.video_paths[stem_type.lower()] = video_path

        self.progress_with_meta("⏫ Uploading to EC2 (if needed)...", 6, total_steps, stem_type, channel, track)
        self.upload_to_ec2_if_needed(base_folder)

        if self.args.get("yt") and self.video_paths:
            self.upload_batch_to_youtube(track)
        else:
            self.update_progress("⏭️ YouTube upload skipped", {"yt_enabled": self.args.get("yt", False)})

        self.mark_complete_with_meta("✅ Drums processing complete", stem_type, channel, track)
