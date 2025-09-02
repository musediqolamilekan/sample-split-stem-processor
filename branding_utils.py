import os
import tempfile
from PIL import Image
from moviepy.editor import CompositeVideoClip, ImageClip

# Define tint per channel.
# Use None (or alpha=0) to apply NO tint.
CHANNEL_TINTS = {
    "Son Got Acapellas": (180, 30, 30),     # Red
    "Son Got Drums": (30, 90, 180),         # Blue
    "Main Channel": None,                   # No tint (baseline look)
    "SGS 2": None,                          # No tint → match Main Channel
    "Sample Split": (255, 215, 0),          # Yellow
}

# Channels that should include intro cards
CHANNELS_WITH_INTRO = {
    "Son Got Acapellas",
    "Son Got Drums",
    "Main Channel",
    "SGS 2",
    "Sample Split",
}

def tint_image(input_path, tint_color=None, alpha=0.4):
    """
    Returns a path to a tinted image. If tint_color is None or alpha <= 0,
    returns the original image path (no tint).
    """
    if not tint_color or alpha <= 0:
        # No tint requested — use the original image unchanged
        return input_path

    img = Image.open(input_path).convert("L")  # grayscale base
    tint = Image.new("RGB", img.size, tint_color)
    blended = Image.blend(tint, img.convert("RGB"), alpha)

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    blended.save(temp_file.name)
    return temp_file.name

def add_intro_card(duration, channel_name, thumbnail_path, stem_type=None):
    """
    Builds the intro card. Backup channel (SGS 2) now uses NO tint,
    same as Main Channel, to keep visuals consistent.
    """
    if channel_name not in CHANNELS_WITH_INTRO or not thumbnail_path or not os.path.exists(thumbnail_path):
        return None

    # Decide tint behavior by channel
    tint_color = CHANNEL_TINTS.get(channel_name, (50, 50, 50))
    # No-tint channels: Main Channel and SGS 2 (to match main)
    alpha = 0.0 if tint_color is None else 0.5

    tinted_thumb_path = tint_image(thumbnail_path, tint_color=tint_color, alpha=alpha)

    bg = (
        ImageClip(tinted_thumb_path)
        .set_duration(duration)
        .resize(height=720)
        .on_color(size=(1280, 720), color=(0, 0, 0), pos="center")
    )

    overlays = []

    # Icon (top-right)
    icon_key = stem_type.lower() if stem_type else channel_name.lower().replace(" ", "_")
    icon_path = f"assets/icons/{icon_key}.png"
    if os.path.exists(icon_path):
        icon = (
            ImageClip(icon_path)
            .resize(height=70)
            .set_position(("right", "top"))
            .margin(right=30, top=20, opacity=0)
            .set_duration(duration)
        )
        overlays.append(icon)

    # Label (bottom-left)
    label_key = channel_name.lower().replace(" ", "_")
    label_path = f"assets/label/{label_key}.png"
    if os.path.exists(label_path):
        label = (
            ImageClip(label_path)
            .resize(height=110)
            .set_position(("left", "bottom"))
            .margin(left=40, bottom=40, opacity=0)
            .set_duration(duration)
        )
        overlays.append(label)

    return CompositeVideoClip([bg, *overlays])
