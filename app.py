import os
import time
import re
import traceback
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__, static_folder='static')
CORS(app)

# Cache configuration
cache = {}
CACHE_TTL = 300

def cache_get(key):
    if key in cache:
        val, ts = cache[key]
        if time.time() - ts < CACHE_TTL:
            return val
        del cache[key]
    return None

def cache_set(key, val):
    cache[key] = (val, time.time())

# Load cookies from file (handles both formats)
def load_cookies_smart():
    try:
        cookie_file = os.path.join(os.path.dirname(__file__), 'cookie_simple.json')
        if not os.path.exists(cookie_file):
            print(f"⚠️ cookie.json not found")
            return None
        
        with open(cookie_file, 'r') as f:
            data = json.load(f)
        
        # Check if it's an array (full export format) or object (simple format)
        if isinstance(data, list):
            # Format: [{"name": "...", "value": "...", ...}, ...]
            cookies_dict = {}
            for cookie in data:
                name = cookie.get('name')
                value = cookie.get('value')
                if name and value:
                    cookies_dict[name] = value
            print(f"✅ Converted {len(cookies_dict)} cookies from array format")
            return cookies_dict
        elif isinstance(data, dict):
            # Format: {"cookie_name": "cookie_value", ...}
            print(f"✅ Loaded {len(data)} cookies from simple format")
            return data
        else:
            print(f"❌ Unknown cookie format")
            return None
            
    except Exception as e:
        print(f"❌ Error loading cookies: {e}")
        return None

# Load cookies
cookies = load_cookies_smart()
cookies_loaded = cookies is not None
cookies_count = len(cookies) if cookies else 0

# yt-dlp configuration
BASE = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'force_ipv4': True,
    'socket_timeout': 30,
    'extractor_retries': 5,
    'retries': 10,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.119 Mobile Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    },
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web_music'],
        }
    },
}

# Add cookies if available
if cookies:
    BASE['cookies'] = cookies
    print(f"✅ Cookies added to yt-dlp config ({cookies_count} cookies)")
else:
    print("⚠️ No cookies - may encounter sign-in errors")

SEARCH_BASE = {**BASE, 'extract_flat': True, 'skip_download': True}

def make_track(e):
    if not e or not e.get('id'):
        return None
    return {
        'id': e['id'],
        'title': e.get('title', 'Unknown')[:100],
        'channel': e.get('uploader') or e.get('channel', 'Unknown'),
        'duration': e.get('duration', 0),
        'thumb': f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg",
    }

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'cookies_loaded': cookies_loaded,
        'cookies_count': cookies_count,
        'timestamp': time.time()
    })

@app.route('/api/search')
def search():
    q = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 20)), 40)
    
    if not q:
        return jsonify({'error': 'No query', 'tracks': []}), 400

    ck = f'search:{q}:{limit}'
    hit = cache_get(ck)
    if hit:
        return jsonify(hit)

    try:
        with yt_dlp.YoutubeDL(SEARCH_BASE) as ydl:
            results = ydl.extract_info(f'ytsearch{limit}:{q}', download=False)

        entries = results.get('entries') or []
        tracks = []
        for e in entries:
            track = make_track(e)
            if track:
                tracks.append(track)
                
        data = {'tracks': tracks, 'query': q}
        cache_set(ck, data)
        return jsonify(data)

    except Exception as ex:
        print('SEARCH ERROR:', traceback.format_exc())
        return jsonify({'error': str(ex), 'tracks': []}), 500

@app.route('/api/trending')
def trending():
    genre = request.args.get('genre', 'popular music')
    ck = f'trending:{genre}'
    hit = cache_get(ck)
    if hit:
        return jsonify(hit)

    try:
        with yt_dlp.YoutubeDL(SEARCH_BASE) as ydl:
            results = ydl.extract_info(f'ytsearch20:{genre}', download=False)

        entries = results.get('entries') or []
        tracks = []
        for e in entries:
            track = make_track(e)
            if track:
                tracks.append(track)
                
        data = {'tracks': tracks, 'genre': genre}
        cache_set(ck, data)
        return jsonify(data)

    except Exception as ex:
        print('TRENDING ERROR:', traceback.format_exc())
        return jsonify({'tracks': [], 'error': str(ex)}), 500

@app.route('/api/stream/<video_id>')
def stream_url(video_id):
    if not re.match(r'^[a-zA-Z0-9_\-]{11}$', video_id):
        return jsonify({'error': 'Invalid ID'}), 400

    ck = f'stream:{video_id}'
    hit = cache_get(ck)
    if hit:
        return jsonify(hit)

    yt_url = f'https://www.youtube.com/watch?v={video_id}'

    formats_to_try = [
        'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio',
        'bestaudio/best',
        '140/251/250/249',
    ]

    for fmt in formats_to_try:
        try:
            opts = {**BASE,
                'format': fmt,
                'skip_download': True,
                'noplaylist': True,
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(yt_url, download=False)

            if not info:
                continue

            stream_url = None
            formats = info.get('formats', [])
            
            for f in formats:
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    if f.get('url'):
                        stream_url = f['url']
                        break
                        
            if not stream_url:
                for f in formats:
                    if f.get('acodec') != 'none' and f.get('url'):
                        stream_url = f['url']
                        break
                        
            if not stream_url:
                stream_url = info.get('url')
                
            if stream_url:
                data = {
                    'url': stream_url,
                    'duration': info.get('duration', 0),
                    'title': info.get('title', 'Unknown'),
                    'channel': info.get('uploader', 'Unknown'),
                    'thumb': f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                    'video_id': video_id,
                }
                cache_set(ck, data)
                return jsonify(data)

        except Exception as ex:
            print(f"Format {fmt} error: {str(ex)[:100]}")
            continue

    return jsonify({'error': 'No playable stream found', 'skippable': True}), 500

@app.route('/api/suggestions')
def suggestions():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'suggestions': []})
        
    try:
        with yt_dlp.YoutubeDL(SEARCH_BASE) as ydl:
            results = ydl.extract_info(f'ytsearch3:{q}', download=False)
        entries = results.get('entries') or []
        suggestions = [e.get('title', '') for e in entries if e][:5]
        return jsonify({'suggestions': suggestions})
    except:
        return jsonify({'suggestions': []})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)