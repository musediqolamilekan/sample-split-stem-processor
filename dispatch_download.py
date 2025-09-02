# dispatch_download.py
import os
import sys
import importlib
import traceback
import torch
import subprocess
from concurrent.futures import ThreadPoolExecutor
import threading

from shared_state import set_progress, get_progress
from content_base import ContentBase

from utils.validators import validate_stems        # validate_stems(base_dir) -> {"ok": bool, "problems": {...}}
from utils.errors import log_failure               # log_failure(batch_id, track_id, reason, details=None)

# --------------------------------------------------------------------------------------
# Path setup
# --------------------------------------------------------------------------------------
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

stem_processing_path = os.path.join(project_root, "stem_processing")
if stem_processing_path not in sys.path:
    sys.path.insert(0, stem_processing_path)

# --------------------------------------------------------------------------------------
# Channel routing (unchanged)
# --------------------------------------------------------------------------------------
CHANNEL_MODULE_MAP = {
    "son_got_acappellas": ("content_download_vocal", "Content_download_vocal"),
    "son_got_drums": ("content_download_drum", "Content_download_drum"),
    "main_channel": ("content_download_main", "Content_download_main"),
    "sgs_2": ("content_download_backup", "Content_download_backup"),
    "sample_split": ("content_download_sample_split", "Content_download_split"),
}

# --------------------------------------------------------------------------------------
# Helpers: pre-process, demucs runners, fallbacks
# --------------------------------------------------------------------------------------

# You can tweak this list; order matters (first wins when valid).
FALLBACK_MODELS = ["htdemucs_6s", "htdemucs_ft", "htdemucs"]

def _prepared_copy_path(uid: str) -> str:
    os.makedirs("MP3", exist_ok=True)
    return os.path.join("MP3", f"{uid}__prep.mp3")

def prepare_input_for_demucs(src_mp3: str, prepared_path: str) -> bool:
    """
    Pre-process input to reduce extraction failures:
      - force 44.1kHz, stereo
      - normalize loudness approx to -14 LUFS (ffmpeg loudnorm)
    Returns True if prepared file is created and looks non-trivial.
    """
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", src_mp3,
            "-ac", "2",
            "-ar", "44100",
            "-af", "loudnorm=I=-14:TP=-2:LRA=11",
            prepared_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        return os.path.exists(prepared_path) and os.path.getsize(prepared_path) > 150_000
    except Exception as e:
        print(f"[PREP] ffmpeg pre-process failed: {e}")
        return False

def model_output_dir(model_name: str, uid: str) -> str:
    # demucs writes to separated/<model_name>/<uid> by default
    return os.path.join("separated", model_name, uid)

def run_demucs_with_model(mp3_path: str, uid: str, device: str, model_name: str):
    """
    Runs demucs with a specific model. Returns subprocess.CompletedProcess or None.
    """
    try:
        print(f"[DEMUCS] Running model: {model_name}")
        return subprocess.run(
            ["demucs", "--mp3", "-n", model_name, "--shifts", "0", "-d", device, mp3_path],
            check=False, capture_output=True, text=True
        )
    except Exception as e:
        print(f"[DEMUCS] Failed to invoke demucs for {model_name}: {e}")
        return None

def run_demucs_with_fallbacks(mp3_path: str, uid: str, device: str, session_id: str):
    """
    Try models in FALLBACK_MODELS until validation passes.
    Returns (model_used, stem_base_path, validation_result) or (None, None, {"ok": False, ...})
    """
    for idx, model in enumerate(FALLBACK_MODELS, start=1):
        set_progress(session_id, {"message": f"🌀 Separating with {model} (attempt {idx})…", "percent": 12})
        proc = run_demucs_with_model(mp3_path, uid, device, model)
        if not proc:
            # couldn't even launch demucs; try next model
            continue

        out_dir = model_output_dir(model, uid)
        if proc.returncode != 0 or not os.path.exists(out_dir):
            print(f"[DEMUCS] Model {model} returned code {proc.returncode}, out_dir exists={os.path.exists(out_dir)}")
            continue

        # ✅ Validate stems
        validation = validate_stems(out_dir)
        if validation.get("ok"):
            return model, out_dir, validation

        print(f"[VALIDATE] Problems with {model}: {validation.get('problems')}")
        # push feedback to UI to explain retry
        set_progress(session_id, {
            "message": f"🔁 Fallback: {model} produced weak stems ({list(validation.get('problems', {}).keys())}); trying next model…",
            "percent": 20
        })

    return None, None, {"ok": False, "problems": {"_": "all_models_failed"}}

# --------------------------------------------------------------------------------------
# Legacy single-model (kept for reference; no longer used by default)
# --------------------------------------------------------------------------------------
def run_demucs_legacy_progress(mp3_path, uid, device, session_id):
    """
    Old streaming-progress runner; kept if you want to keep line-by-line updates.
    Not used by default since we now do fallbacks via run_demucs_with_fallbacks().
    """
    try:
        set_progress(session_id, {
            "message": "🌀 Starting stem separation…",
            "percent": 11
        })

        process = subprocess.Popen(
            ["demucs", "--mp3", "-n", "htdemucs_6s", "--shifts", "0", "-d", device, mp3_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )

        elapsed = 0
        while True:
            line = process.stdout.readline()
            if line == "" and process.poll() is not None:
                break

            if line:
                print(f"[DEMUCS] {line.strip()}")
                elapsed += 1
                if elapsed % 10 == 0:
                    percent = min(12 + (elapsed // 2), 44)
                    set_progress(session_id, {"message": f"⏳ Separating… {elapsed}s", "percent": percent})

            if elapsed >= 600:
                process.kill()
                set_progress(session_id, {"message": "❌ Timeout: separation took over 10 minutes", "percent": 0})
                return None

        return process

    except Exception as e:
        set_progress(session_id, {"message": f"❌ Demucs error: {str(e)}", "percent": 0})
        return None

# --------------------------------------------------------------------------------------
# Main dispatch
# --------------------------------------------------------------------------------------
def dispatch_stem_processing(track_id: str, selected_channels: list, args: dict, session_id: str = "default"):
    print(f"\n🚀 Dispatching stem processing for track: {track_id}")
    base = ContentBase({**args, "session_id": session_id})

    # Fetch track info
    track_info = base.get_track_info(track_id)
    if not track_info:
        set_progress(session_id, {"message": "❌ Failed to get track info", "percent": 0})
        log_failure(session_id, track_id, "track_info", {"message": "Failed to get track info"})
        return

    args["track_info"] = track_info

    # Download audio
    base.update_progress("🎵 Downloading track audio…", {"track_id": track_id})
    uid, mp3_path = base.download_audio(track_info["name"], track_info["artist"])
    if not uid or not os.path.exists(mp3_path):
        set_progress(session_id, {"message": "❌ Audio download failed", "percent": 0})
        log_failure(session_id, track_id, "download_audio", {"uid": uid, "mp3_path": mp3_path})
        return

    args["universal_id"] = uid
    args["mp3_path"] = mp3_path

    # Pre-process input (resample + loudness normalize)
    prep_path = _prepared_copy_path(uid)
    if prepare_input_for_demucs(mp3_path, prep_path):
        mp3_for_split = prep_path
        print(f"[PREP] Using prepared audio at {prep_path}")
    else:
        mp3_for_split = mp3_path
        print(f"[PREP] Using original audio (prep failed or skipped)")

    # If cached *validated* stems exist under any model dir, reuse first valid.
    cached_dir = None
    cached_model = None
    for model in FALLBACK_MODELS:
        test_dir = model_output_dir(model, uid)
        if os.path.exists(test_dir):
            v = validate_stems(test_dir)
            if v.get("ok"):
                cached_dir = test_dir
                cached_model = model
                break

    if cached_dir:
        args["stem_base_path"] = cached_dir
        set_progress(session_id, {"message": f"✅ Using cached stems ({cached_model})", "percent": 45})
    else:
        # Run Demucs with fallbacks and validate
        set_progress(session_id, {"message": "🌀 Separating stems…", "percent": 12})
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        model_used, stem_base_path, validation = run_demucs_with_fallbacks(mp3_for_split, uid, device, session_id)
        if not model_used:
            msg = "❌ Stem separation failed on all models"
            set_progress(session_id, {"message": msg, "percent": 0})
            log_failure(session_id, track_id, "separation_failed", {"problems": validation.get("problems")})
            return

        args["stem_base_path"] = stem_base_path
        set_progress(session_id, {"message": f"✅ Separation complete with {model_used}", "percent": 45})

    # Progress metas
    progress = get_progress(session_id)
    if progress:
        progress.update({
            "message": "🟢 Processing channels…",
            "meta": {"completed": 0, "total": len(selected_channels)},
            "percent": 46
        })
        set_progress(session_id, progress)

    # Process each selected channel; on failure, log and continue
    for channel_key in selected_channels:
        if channel_key not in CHANNEL_MODULE_MAP:
            log_failure(session_id, track_id, "unknown_channel", {"channel_key": channel_key})
            continue

        try:
            progress = get_progress(session_id) or {}
            meta = progress.get("meta", {}) if progress else {}
            if progress:
                progress["message"] = f"⚙️ Uploading {channel_key.upper()}…"
                meta["channel"] = channel_key
                progress["meta"] = meta
                set_progress(session_id, progress)

            module_name, class_name = CHANNEL_MODULE_MAP[channel_key]
            module = importlib.import_module(module_name)
            processor_class = getattr(module, class_name)
            processor = processor_class({**args, "channel": channel_key, "session_id": session_id})
            processor.download(track_id)

            # Step done
            progress = get_progress(session_id) or {}
            meta = progress.get("meta", {})
            meta["completed"] = int(meta.get("completed", 0)) + 1
            meta["channel"] = channel_key
            total = int(meta.get("total", 1))
            progress["meta"] = meta
            progress["percent"] = 46 + int((meta["completed"] / total) * 54)
            progress["message"] = f"✅ {channel_key.upper()} done"
            set_progress(session_id, progress)

        except Exception as e:
            traceback.print_exc()
            log_failure(session_id, track_id, "channel_processing", {
                "channel_key": channel_key,
                "error": str(e),
                "traceback": traceback.format_exc()
            })
            # Don’t break the whole playlist; continue with next channel
            progress = get_progress(session_id) or {}
            progress["message"] = f"❌ Error processing {channel_key.upper()} — continuing"
            set_progress(session_id, progress)
            continue

    # Finalize
    final = get_progress(session_id) or {}
    final["message"] = "✅ All processing complete"
    final["percent"] = 100
    set_progress(session_id, final)

# --------------------------------------------------------------------------------------
# Batch runner
# --------------------------------------------------------------------------------------
def process_all_tracks(
    track_ids: list,
    selected_channels: list,
    args: dict = None,
    session_id: str = "batch",
    max_concurrent: int = 2,
    per_track_args: dict = None
):
    """
    Run multiple tracks with limited concurrency.
    If a track fails, it logs and other tracks continue.
    """
    semaphore = threading.Semaphore(max_concurrent)

    def run_with_semaphore(track_id, sess_id):
        with semaphore:
            merged_args = args.copy() if args else {}
            if per_track_args and track_id in per_track_args:
                merged_args.update(per_track_args[track_id])
            try:
                dispatch_stem_processing(track_id, selected_channels, merged_args, sess_id)
            except Exception as e:
                # extreme guard: never kill the batch
                traceback.print_exc()
                log_failure(sess_id, track_id, "dispatch_uncaught", {"error": str(e)})
                set_progress(sess_id, {"message": f"❌ Uncaught error for {track_id} — continuing", "percent": 0})

    with ThreadPoolExecutor(max_workers=len(track_ids) or 1) as executor:
        for track_id in track_ids:
            full_session_id = f"{session_id}__{track_id}"
            executor.submit(run_with_semaphore, track_id, full_session_id)
