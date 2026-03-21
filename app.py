import os
import time
import re
import traceback
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

# yt-dlp configuration
BASE = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'force_ipv4': True,
    'socket_timeout': 30,
    'extractor_retries': 3,
    'file_access_retries': 3,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    },
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web_music'],
            'skip': ['dash', 'hls'],
        }
    },
}

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

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def sw():
    r = send_from_directory('static', 'sw.js')
    r.headers['Service-Worker-Allowed'] = '/'
    r.headers['Content-Type'] = 'application/javascript'
    return r

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'timestamp': time.time()})

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

    try:
        # Try audio-only formats first
        opts = {**BASE,
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
            'skip_download': True,
            'noplaylist': True,
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(yt_url, download=False)

        if not info:
            return jsonify({'error': 'No info extracted'}), 500

        # Get the best audio URL
        stream_url = None
        formats = info.get('formats', [])
        
        # Look for audio-only formats
        for f in formats:
            if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                if f.get('url'):
                    stream_url = f['url']
                    break
                    
        # Fallback to any format with audio
        if not stream_url:
            for f in formats:
                if f.get('acodec') != 'none' and f.get('url'):
                    stream_url = f['url']
                    break
                    
        # Last resort: use direct URL
        if not stream_url:
            stream_url = info.get('url')
            
        if not stream_url:
            return jsonify({'error': 'No stream URL found'}), 500

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

    except yt_dlp.utils.ExtractorError as ex:
        error_msg = str(ex).lower()
        blocked = ['sign in', 'login', 'private', 'members only', 'age', 'unavailable']
        if any(w in error_msg for w in blocked):
            return jsonify({'error': 'unavailable', 'skippable': True}), 403
        return jsonify({'error': str(ex), 'skippable': True}), 500
    except Exception as ex:
        print('STREAM ERROR:', traceback.format_exc())
        return jsonify({'error': str(ex), 'skippable': True}), 500

@app.route('/api/suggestions')
def suggestions():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'suggestions': []})
        
    ck = f'suggest:{q}'
    hit = cache_get(ck)
    if hit:
        return jsonify(hit)
        
    try:
        with yt_dlp.YoutubeDL(SEARCH_BASE) as ydl:
            results = ydl.extract_info(f'ytsearch3:{q}', download=False)
        entries = results.get('entries') or []
        suggestions = [e.get('title', '') for e in entries if e][:5]
        data = {'suggestions': suggestions}
        cache_set(ck, data)
        return jsonify(data)
    except:
        return jsonify({'suggestions': []})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)