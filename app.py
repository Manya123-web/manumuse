import os
import time
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
BASE_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

SEARCH_OPTS = {**BASE_OPTS, 'extract_flat': True, 'skip_download': True}

def parse_track(e):
    if not e or not e.get('id'):
        return None
    return {
        'id': e['id'],
        'title': e.get('title') or 'Unknown',
        'channel': e.get('uploader') or e.get('channel') or 'Unknown',
        'duration': e.get('duration') or 0,
        'thumb': f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg",
    }

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/api/search')
def search():
    q = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 20)), 40)
    if not q:
        return jsonify({'error': 'No query'}), 400

    ck = f'search:{q}:{limit}'
    cached = cache_get(ck)
    if cached:
        return jsonify(cached)

    try:
        with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
            results = ydl.extract_info(f'ytsearch{limit}:{q}', download=False)
        tracks = [t for t in (parse_track(e) for e in (results.get('entries') or [])) if t]
        data = {'tracks': tracks, 'query': q}
        cache_set(ck, data)
        return jsonify(data)
    except Exception as ex:
        return jsonify({'error': str(ex), 'tracks': []}), 500


@app.route('/api/stream/<video_id>')
def stream_url(video_id):
    ck = f'stream:{video_id}'
    cached = cache_get(ck)
    if cached:
        return jsonify(cached)

    url = f'https://www.youtube.com/watch?v={video_id}'

    # Try multiple format strategies so something always plays
    opts = {
        **BASE_OPTS,
        'format': 'bestaudio/best',
        'noplaylist': True,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        return jsonify({'error': 'No info', 'skippable': True}), 500

    formats = info.get('formats', [])

    # Filter only pure audio
    audio_formats = [
        f for f in formats
        if f.get('acodec') != 'none' and f.get('vcodec') == 'none'
    ]

    # Sort → prefer m4a + highest bitrate
    audio_formats.sort(
        key=lambda x: (x.get('ext') != 'm4a', -(x.get('abr') or 0))
    )

    chosen = audio_formats[0] if audio_formats else None

    if not chosen:
    # fallback to any playable format
        for f in formats:   
            if f.get('url'):
                chosen = f
                break

    if not chosen:
        return jsonify({'error': 'No playable stream', 'skippable': True}), 500

    stream = chosen.get('url')

    data = {
        'url': stream,
        'mime': 'audio/mp4',
        'duration': info.get('duration') or 0,
        'title': info.get('title') or 'Unknown',
        'channel': info.get('uploader') or 'Unknown',
        'thumb': f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
        'video_id': video_id,
    }

    cache_set(ck, data)
    return jsonify(data)


@app.route('/api/trending')
def trending():
    genre = request.args.get('genre', 'music hits 2025')
    ck = f'trending:{genre}'
    cached = cache_get(ck)
    if cached:
        return jsonify(cached)

    try:
        with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
            results = ydl.extract_info(f'ytsearch25:{genre}', download=False)
        tracks = [t for t in (parse_track(e) for e in (results.get('entries') or [])) if t]
        data = {'tracks': tracks, 'genre': genre}
        cache_set(ck, data)
        return jsonify(data)
    except Exception as ex:
        return jsonify({'error': str(ex), 'tracks': []}), 500


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
        with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
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
