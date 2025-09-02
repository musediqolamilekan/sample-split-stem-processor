from playwright.sync_api import sync_playwright, TimeoutError
from bs4 import BeautifulSoup
import time
import os

def get_bpm_key(track_name: str, artist_name: str, track_id: str) -> tuple[int, str]:
    def slugify(text):
        return text.strip().replace(" ", "-")

    name_slug = slugify(track_name)
    artist_slug = slugify(artist_name)
    url = f"https://tunebat.com/Info/{name_slug}-{artist_slug}/{track_id}"

    print(f"🌐 Constructed Tunebat URL: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,  # Set to False to avoid Cloudflare block
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage"
                ]
            )
            page = browser.new_page()
            print("🕸️ Navigating to page...")
            page.goto(url, timeout=120000)

            selector = "div.yIPfN span.ant-typography-secondary"
            print("⏳ Waiting for BPM/Key block...")

            max_attempts = 240  # wait up to 20 mins
            for attempt in range(max_attempts):
                try:
                    page.wait_for_selector(selector, timeout=5000)
                    print(f"✅ Element found after {attempt * 5} seconds.")
                    break
                except TimeoutError:
                    print(f"⏳ Still waiting... ({(attempt + 1) * 5}s)")
            else:
                print(f"❌ Timeout after {max_attempts * 5}s")
                browser.close()
                return 0, "Unknown"

            html = page.content()

            # Save HTML for debugging
            debug_dir = "tunebat_debug"
            os.makedirs(debug_dir, exist_ok=True)
            debug_path = os.path.join(debug_dir, f"{track_id}.html")
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
                print(f"💾 Saved HTML to {debug_path}")

            browser.close()
            print("✅ Page loaded and browser closed.")

        # Parse HTML for BPM and Key
        soup = BeautifulSoup(html, "html.parser")
        bpm = 0
        key = "Unknown"

        blocks = soup.find_all("div", class_="yIPfN")
        for block in blocks:
            label = block.find("span", class_="ant-typography-secondary")
            value = block.find("h3")
            if not label or not value:
                continue

            label_text = label.text.strip().lower()
            value_text = value.text.strip()

            if label_text == "bpm":
                try:
                    bpm = int(value_text)
                except ValueError:
                    bpm = 0
            elif label_text == "key":
                key = value_text

        print(f"🎼 Extracted BPM: {bpm}, Key: {key}")
        return bpm, key

    except Exception as e:
        print(f"❌ Failed to get BPM/Key from Tunebat: {e}")
        return 0, "Unknown"