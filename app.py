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

# Load cookies
cookies = None
cookies_loaded = False
cookies_count = 0

try:
    cookie_file = os.path.join(os.path.dirname(__file__), 'cookie.json')
    print(f"Looking for cookies at: {cookie_file}")
    
    if os.path.exists(cookie_file):
        with open(cookie_file, 'r') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            cookies_dict = {}
            for cookie in data:
                name = cookie.get('name')
                value = cookie.get('value')
                if name and value:
                    cookies_dict[name] = value
            cookies = cookies_dict
            cookies_count = len(cookies)
            cookies_loaded = True
            print(f"✅ Loaded {cookies_count} cookies")
        elif isinstance(data, dict):
            cookies = data
            cookies_count = len(data)
            cookies_loaded = True
            print(f"✅ Loaded {cookies_count} cookies from dict")
    else:
        print(f"⚠️ cookie.json not found")
except Exception as e:
    print(f"❌ Error loading cookies: {e}")

# yt-dlp configuration
BASE = {
    'quiet': False,  # Set to False to see what's happening
    'no_warnings': False,
    'nocheckcertificate': True,
    'force_ipv4': True,
    'socket_timeout': 30,
    'extractor_retries': 5,
    'retries': 10,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    },
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web', 'web_music'],
            'skip': ['webpage'],
        }
    },
}

# Add cookies if available
if cookies:
    BASE['cookies'] = cookies
    print("✅ Cookies added to yt-dlp")

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
        'ytdlp_version': yt_dlp.version.__version__,
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
        print(f"Searching for: {q}")
        with yt_dlp.YoutubeDL(SEARCH_BASE) as ydl:
            results = ydl.extract_info(f'ytsearch{limit}:{q}', download=False)
        
        print(f"Got results: {results is not None}")
        entries = results.get('entries') or []
        print(f"Entries count: {len(entries)}")
        
        tracks = []
        for e in entries:
            track = make_track(e)
            if track:
                tracks.append(track)
        
        print(f"Tracks created: {len(tracks)}")
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
        print(f"Trending for: {genre}")
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
        'best[acodec=opus]/best',
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
            print(f"Format {fmt} error: {str(ex)[:200]}")
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