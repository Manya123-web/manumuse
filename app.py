import os
import time
import re
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__, static_folder='static')
CORS(app)

# ── Cache ──────────────────────────────────────────────────────────────────────
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

# ── yt-dlp base config ─────────────────────────────────────────────────────────
BASE = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    },
}

SEARCH_BASE = {**BASE, 'extract_flat': True, 'skip_download': True}

def make_track(e):
    if not e or not e.get('id'):
        return None
    return {
        'id': e['id'],
        'title': e.get('title') or 'Unknown',
        'channel': e.get('uploader') or e.get('channel') or 'Unknown',
        'duration': e.get('duration') or 0,
        'thumb': f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg",
    }

# ── Routes ─────────────────────────────────────────────────────────────────────

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
    return jsonify({'status': 'ok'})


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
        # ✅ Correct yt-dlp search syntax
        with yt_dlp.YoutubeDL(SEARCH_BASE) as ydl:
            results = ydl.extract_info(f'ytsearch{limit}:{q}', download=False)

        tracks = [t for t in (make_track(e) for e in (results.get('entries') or [])) if t]
        data = {'tracks': tracks, 'query': q}
        cache_set(ck, data)
        return jsonify(data)

    except Exception as ex:
        print(f'SEARCH ERROR: {ex}')
        return jsonify({'error': str(ex), 'tracks': []}), 500


@app.route('/api/trending')
def trending():
    genre = request.args.get('genre', 'music hits 2025')
    ck = f'trending:{genre}'
    hit = cache_get(ck)
    if hit:
        return jsonify(hit)

    try:
        # ✅ Correct yt-dlp search syntax
        with yt_dlp.YoutubeDL(SEARCH_BASE) as ydl:
            results = ydl.extract_info(f'ytsearch25:{genre}', download=False)

        tracks = [t for t in (make_track(e) for e in (results.get('entries') or [])) if t]
        data = {'tracks': tracks, 'genre': genre}
        cache_set(ck, data)
        return jsonify(data)

    except Exception as ex:
        print(f'TRENDING ERROR: {ex}')
        return jsonify({'tracks': [], 'error': str(ex)})


@app.route('/api/stream/<video_id>')
def stream_url(video_id):
    if not re.match(r'^[a-zA-Z0-9_\-]{6,15}$', video_id):
        return jsonify({'error': 'Invalid ID'}), 400

    ck = f'stream:{video_id}'
    hit = cache_get(ck)
    if hit:
        return jsonify(hit)

    yt_url = f'https://www.youtube.com/watch?v={video_id}'
    last_err = 'Unknown error'

    # Try multiple format strategies
    for fmt in [
        'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio',
        '140/251/bestaudio',
        'worstaudio/worst',
    ]:
        try:
            opts = {**BASE, 'format': fmt, 'skip_download': True, 'noplaylist': True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(yt_url, download=False)

            if not info:
                continue

            fmts = info.get('formats') or []

            # Find best audio-only format
            chosen = None
            for f in reversed(fmts):
                if f.get('acodec') not in ('none', None) and f.get('vcodec') in ('none', None) and f.get('url'):
                    chosen = f
                    break
            # Fallback: any format with audio
            if not chosen:
                for f in reversed(fmts):
                    if f.get('acodec') not in ('none', None) and f.get('url'):
                        chosen = f
                        break

            stream = (chosen['url'] if chosen else None) or info.get('url')
            if not stream:
                continue

            ext = (chosen.get('ext') if chosen else None) or info.get('ext') or 'mp4'
            mime = {'m4a': 'audio/mp4', 'webm': 'audio/webm', 'mp4': 'audio/mp4'}.get(ext, 'audio/mp4')

            data = {
                'url': stream,
                'mime': mime,
                'duration': info.get('duration') or 0,
                'title': info.get('title') or 'Unknown',
                'channel': info.get('uploader') or info.get('channel') or 'Unknown',
                'thumb': f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                'video_id': video_id,
            }
            cache_set(ck, data)
            return jsonify(data)

        except yt_dlp.utils.ExtractorError as ex:
            last_err = str(ex)
            blocked = ['sign in', 'login', 'private', 'members only', 'age-restrict',
                       'not available', 'removed', 'copyright', 'unavailable']
            if any(w in last_err.lower() for w in blocked):
                return jsonify({'error': 'unavailable', 'skippable': True}), 403
            continue
        except Exception as ex:
            last_err = str(ex)
            continue

    return jsonify({'error': last_err[:200], 'skippable': True}), 500


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
