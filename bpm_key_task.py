from concurrent.futures import ThreadPoolExecutor
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from tunebat_helper import get_bpm_key  

CLIENT_ID = "fbf9f3a2da0b44758a496ca7fa8a9290"
CLIENT_SECRET = "c47363028a7c478285fe1e27ecb4428f"

def crawl_bpm_keys_batch(track_ids):
    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    ))

    def crawl(track_id):
        try:
            track = sp.track(track_id)
            artist = track["artists"][0]["name"]
            title = track["name"]
            bpm, key = get_bpm_key(title, artist, track_id)
            print(f"✅ {artist} - {title} → BPM: {bpm}, Key: {key}")
        except Exception as e:
            print(f"❌ Failed for {track_id}: {e}")

    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(crawl, track_ids)

# Replace with real Spotify track IDs from a playlist
track_ids = [
    "4cOdK2wGLETKBW3PvgPWqT",
    "3n3Ppam7vgaVa1iaRUc9Lp",
    "6habFhsOp2NvshLv26DqMb"
]

if __name__ == "__main__":
    crawl_bpm_keys_batch(track_ids)
