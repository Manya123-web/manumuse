import json
import yt_dlp

# Load cookies
with open('cookie.json', 'r') as f:
    cookies = json.load(f)

print(f"✅ Loaded {len(cookies)} cookies")

# Test yt-dlp with cookies
opts = {
    'quiet': False,
    'cookies': cookies,
    'extractor_args': {'youtube': {'player_client': ['android']}}
}

try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info('https://www.youtube.com/watch?v=dQw4w9WgXcQ', download=False)
        print(f"✅ Success! Title: {info.get('title')}")
except Exception as e:
    print(f"❌ Error: {e}")