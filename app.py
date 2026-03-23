import os
import time
import re
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__, static_folder='static')
CORS(app)

# ─── Cache ────────────────────────────────────────────────────────────────────
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

# ─── yt-dlp options ───────────────────────────────────────────────────────────
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

FLAT_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'extract_flat': True,
    'skip_download': True,
    'nocheckcertificate': True,
    'http_headers': HEADERS,
}

def parse_track(e):
    if not e or not e.get('id'):
        return None
    return {
        'id': e['id'],
        'title': e.get('title') or 'Unknown',
        'channel': e.get('uploader') or e.get('channel') or e.get('channel_id') or 'Unknown',
        'duration': e.get('duration') or 0,
        'thumb': f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg",
    }

# ─── ROUTES ───────────────────────────────────────────────────────────────────

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
    return jsonify({'status': 'ok', 'version': '4.0'})


@app.route('/api/search')
def search():
    q = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 20)), 40)
    if not q:
        return jsonify({'error': 'No query', 'tracks': []}), 400

    ck = f'search:{q}:{limit}'
    cached = cache_get(ck)
    if cached:
        return jsonify(cached)

    try:
        # ✅ KEY FIX: use ytsearchN:query — NOT default_search + bare query
        with yt_dlp.YoutubeDL(FLAT_OPTS) as ydl:
            results = ydl.extract_info(f'ytsearch{limit}:{q}', download=False)

        tracks = [t for t in (parse_track(e) for e in (results.get('entries') or [])) if t]
        data = {'tracks': tracks, 'query': q}
        cache_set(ck, data)
        return jsonify(data)

    except Exception as ex:
        print(f'SEARCH ERROR: {ex}')
        return jsonify({'error': str(ex), 'tracks': []}), 500


@app.route('/api/stream/<video_id>')
def stream_url(video_id):
    if not re.match(r'^[a-zA-Z0-9_\-]{6,15}$', video_id):
        return jsonify({'error': 'Invalid video ID'}), 400

    ck = f'stream:{video_id}'
    cached = cache_get(ck)
    if cached:
        return jsonify(cached)

    yt_url = f'https://www.youtube.com/watch?v={video_id}'
    last_error = 'Unknown error'

    for fmt in ['bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio', '140/251/bestaudio', 'worstaudio/worst']:
        try:
            opts = {**FLAT_OPTS, 'format': fmt, 'extract_flat': False, 'noplaylist': True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(yt_url, download=False)

            if not info:
                continue

            formats = info.get('formats') or []
            chosen = None

            for f in reversed(formats):
                if f.get('acodec') not in ('none', None) and f.get('vcodec') in ('none', None) and f.get('url'):
                    chosen = f
                    break

            if not chosen:
                for f in reversed(formats):
                    if f.get('acodec', 'none') != 'none' and f.get('url'):
                        chosen = f
                        break

            stream = (chosen['url'] if chosen else None) or info.get('url')
            if not stream:
                continue

            ext = (chosen.get('ext') if chosen else None) or info.get('ext') or 'mp4'
            mime_map = {'m4a': 'audio/mp4', 'webm': 'audio/webm', 'mp4': 'audio/mp4', 'ogg': 'audio/ogg'}

            data = {
                'url': stream,
                'mime': mime_map.get(ext, 'audio/mp4'),
                'duration': info.get('duration') or 0,
                'title': info.get('title') or 'Unknown',
                'channel': info.get('uploader') or info.get('channel') or 'Unknown',
                'thumb': f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                'video_id': video_id,
            }
            cache_set(ck, data)
            return jsonify(data)

        except yt_dlp.utils.ExtractorError as ex:
            last_error = str(ex)
            skip_words = ['sign in', 'login', 'private video', 'members only',
                          'age-restricted', 'not available', 'been removed',
                          'copyright', 'unavailable', 'blocked']
            if any(w in last_error.lower() for w in skip_words):
                return jsonify({'error': 'unavailable', 'reason': last_error[:120], 'skippable': True}), 403
            continue

        except Exception as ex:
            last_error = str(ex)
            continue

    return jsonify({'error': last_error[:200], 'skippable': True}), 500


@app.route('/api/trending')
def trending():
    genre = request.args.get('genre', 'music hits 2025')
    ck = f'trending:{genre}'
    cached = cache_get(ck)
    if cached:
        return jsonify(cached)

    try:
        # ✅ KEY FIX: use ytsearch25:query — NOT default_search + bare query
        with yt_dlp.YoutubeDL(FLAT_OPTS) as ydl:
            results = ydl.extract_info(f'ytsearch25:{genre}', download=False)

        tracks = [t for t in (parse_track(e) for e in (results.get('entries') or [])) if t]
        data = {'tracks': tracks, 'genre': genre}
        cache_set(ck, data)
        return jsonify(data)

    except Exception as ex:
        print(f'TRENDING ERROR: {ex}')
        return jsonify({'tracks': [], 'error': str(ex)}), 200


@app.route('/api/suggestions')
def suggestions():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'suggestions': []})
    ck = f'suggest:{q}'
    cached = cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        with yt_dlp.YoutubeDL(FLAT_OPTS) as ydl:
            results = ydl.extract_info(f'ytsearch5:{q}', download=False)
        sugg = [e.get('title', '') for e in (results.get('entries') or []) if e]
        data = {'suggestions': sugg[:5]}
        cache_set(ck, data)
        return jsonify(data)
    except:
        return jsonify({'suggestions': []})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
