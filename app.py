import os
import json
import time
import threading
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
import yt_dlp

app = Flask(__name__, static_folder='static')
CORS(app)

# ─── Simple in-memory cache so same searches don't re-fetch ───────────────────
cache = {}
CACHE_TTL = 300  # 5 minutes

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
YDL_SEARCH_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'extract_flat': True,
    'skip_download': True,
}

YDL_STREAM_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio',
    'skip_download': True,
    'nocheckcertificate': True,
}

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/search')
def search():
    q = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 20)), 40)
    if not q:
        return jsonify({'error': 'No query'}), 400

    cache_key = f'search:{q}:{limit}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)

    try:
        with yt_dlp.YoutubeDL(YDL_SEARCH_OPTS) as ydl:
            results = ydl.extract_info(f'ytsearch{limit}:{q}', download=False)
            entries = results.get('entries', [])

        tracks = []
        for e in entries:
            if not e:
                continue
            tracks.append({
                'id': e.get('id', ''),
                'title': e.get('title', 'Unknown'),
                'channel': e.get('uploader') or e.get('channel') or 'Unknown',
                'duration': e.get('duration', 0),
                'thumb': (
                    f"https://i.ytimg.com/vi/{e.get('id', '')}/mqdefault.jpg"
                ),
            })

        data = {'tracks': tracks, 'query': q}
        cache_set(cache_key, data)
        return jsonify(data)

    except Exception as ex:
        return jsonify({'error': str(ex)}), 500


@app.route('/api/stream/<video_id>')
def stream_url(video_id):
    """Return a direct audio stream URL for the given video ID."""
    cache_key = f'stream:{video_id}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)

    try:
        url = f'https://www.youtube.com/watch?v={video_id}'
        with yt_dlp.YoutubeDL(YDL_STREAM_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)

        # Pick best audio format
        formats = info.get('formats', [])
        audio_fmt = None
        for f in reversed(formats):
            if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                audio_fmt = f
                break
        if not audio_fmt and formats:
            audio_fmt = formats[-1]

        stream_url = audio_fmt.get('url') if audio_fmt else info.get('url')
        mime = audio_fmt.get('ext', 'mp4') if audio_fmt else 'mp4'
        duration = info.get('duration', 0)
        title = info.get('title', 'Unknown')
        channel = info.get('uploader') or info.get('channel') or 'Unknown'
        thumb = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"

        data = {
            'url': stream_url,
            'mime': f'audio/{mime}',
            'duration': duration,
            'title': title,
            'channel': channel,
            'thumb': thumb,
            'video_id': video_id,
        }
        cache_set(cache_key, data)
        return jsonify(data)

    except Exception as ex:
        return jsonify({'error': str(ex)}), 500


@app.route('/api/trending')
def trending():
    genre = request.args.get('genre', 'music hits 2025')
    cache_key = f'trending:{genre}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)

    try:
        with yt_dlp.YoutubeDL(YDL_SEARCH_OPTS) as ydl:
            results = ydl.extract_info(f'ytsearch25:{genre}', download=False)
            entries = results.get('entries', [])

        tracks = []
        for e in entries:
            if not e:
                continue
            tracks.append({
                'id': e.get('id', ''),
                'title': e.get('title', 'Unknown'),
                'channel': e.get('uploader') or e.get('channel') or 'Unknown',
                'duration': e.get('duration', 0),
                'thumb': f"https://i.ytimg.com/vi/{e.get('id', '')}/mqdefault.jpg",
            })

        data = {'tracks': tracks, 'genre': genre}
        cache_set(cache_key, data)
        return jsonify(data)

    except Exception as ex:
        return jsonify({'error': str(ex)}), 500


@app.route('/api/suggestions')
def suggestions():
    """Autocomplete suggestions based on partial query."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'suggestions': []})
    # Return quick search results as suggestions
    cache_key = f'suggest:{q}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    try:
        with yt_dlp.YoutubeDL(YDL_SEARCH_OPTS) as ydl:
            results = ydl.extract_info(f'ytsearch5:{q}', download=False)
            entries = results.get('entries', [])
        sugg = [e.get('title', '') for e in entries if e]
        data = {'suggestions': sugg}
        cache_set(cache_key, data)
        return jsonify(data)
    except:
        return jsonify({'suggestions': []})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
