import os
import time
import re
import requests
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
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

def extract_stream(video_id):
    """Extract direct audio stream URL using multiple client strategies."""
    yt_url = f'https://www.youtube.com/watch?v={video_id}'

    strategies = [
        # Android client — bypasses most bot detection on server IPs
        {
            'format': 'bestaudio/best',
            'quiet': True, 'no_warnings': True,
            'nocheckcertificate': True, 'skip_download': True, 'noplaylist': True,
            'extractor_args': {'youtube': {'player_client': ['android']}},
            'http_headers': HEADERS,
        },
        # iOS client fallback
        {
            'format': 'bestaudio/best',
            'quiet': True, 'no_warnings': True,
            'nocheckcertificate': True, 'skip_download': True, 'noplaylist': True,
            'extractor_args': {'youtube': {'player_client': ['ios']}},
            'http_headers': HEADERS,
        },
        # TV client — another bypass option
        {
            'format': 'bestaudio/best',
            'quiet': True, 'no_warnings': True,
            'nocheckcertificate': True, 'skip_download': True, 'noplaylist': True,
            'extractor_args': {'youtube': {'player_client': ['tv_embedded']}},
            'http_headers': HEADERS,
        },
    ]

    for opts in strategies:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(yt_url, download=False)

            if not info:
                continue

            formats = info.get('formats') or []

            # Prefer pure audio (no video) — m4a preferred for best compatibility
            chosen = None
            for f in reversed(formats):
                ext = f.get('ext', '')
                if (f.get('acodec') not in ('none', None)
                        and f.get('vcodec') in ('none', None)
                        and f.get('url')
                        and ext in ('m4a', 'webm', 'mp4', 'aac')):
                    chosen = f
                    break

            # Any audio format
            if not chosen:
                for f in reversed(formats):
                    if f.get('acodec', 'none') != 'none' and f.get('url'):
                        chosen = f
                        break

            stream_url = (chosen['url'] if chosen else None) or info.get('url')
            if not stream_url:
                continue

            ext = (chosen.get('ext') if chosen else None) or info.get('ext') or 'mp4'
            mime_map = {'m4a': 'audio/mp4', 'webm': 'audio/webm', 'mp4': 'audio/mp4', 'aac': 'audio/aac', 'ogg': 'audio/ogg'}

            return {
                'stream_url': stream_url,
                'mime': mime_map.get(ext, 'audio/mp4'),
                'duration': info.get('duration') or 0,
                'title': info.get('title') or 'Unknown',
                'channel': info.get('uploader') or info.get('channel') or 'Unknown',
                'ext': ext,
            }, None

        except yt_dlp.utils.ExtractorError as ex:
            err = str(ex)
            skip_words = ['sign in', 'login', 'private video', 'members only',
                          'age-restricted', 'not available', 'been removed',
                          'copyright', 'unavailable', 'blocked']
            if any(w in err.lower() for w in skip_words):
                return None, {'error': 'unavailable', 'reason': err[:120], 'skippable': True}
            continue
        except Exception as ex:
            print(f'EXTRACT ERROR: {ex}')
            continue

    return None, {'error': 'Could not extract stream after all attempts', 'skippable': True}

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
    return jsonify({'status': 'ok', 'version': '5.0'})


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
def stream_info(video_id):
    """Returns stream metadata + a proxy URL the browser should use."""
    if not re.match(r'^[a-zA-Z0-9_\-]{6,15}$', video_id):
        return jsonify({'error': 'Invalid video ID'}), 400

    ck = f'streaminfo:{video_id}'
    cached = cache_get(ck)
    if cached:
        # Return the proxy URL pointing back to our server
        return jsonify({**cached, 'url': f'/api/proxy/{video_id}'})

    result, err = extract_stream(video_id)
    if err:
        return jsonify(err), 403 if err.get('error') == 'unavailable' else 500

    # Cache the raw stream data (including the direct URL for proxying)
    cache_set(ck, result)

    return jsonify({
        'url': f'/api/proxy/{video_id}',   # ← browser uses our proxy, not direct YT URL
        'mime': result['mime'],
        'duration': result['duration'],
        'title': result['title'],
        'channel': result['channel'],
        'thumb': f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
        'video_id': video_id,
    })


@app.route('/api/proxy/<video_id>')
def proxy_audio(video_id):
    """
    Proxies the YouTube audio stream through our server.
    This solves ERR_CONNECTION_TIMED_OUT — the browser talks to us,
    we fetch from YouTube server-side and pipe it back.
    Supports Range requests so seeking works.
    """
    if not re.match(r'^[a-zA-Z0-9_\-]{6,15}$', video_id):
        return 'Invalid ID', 400

    # Get cached stream info
    ck = f'streaminfo:{video_id}'
    stream_data = cache_get(ck)

    if not stream_data:
        # Not cached — extract fresh
        result, err = extract_stream(video_id)
        if err or not result:
            return 'Stream unavailable', 503
        cache_set(ck, result)
        stream_data = result

    stream_url = stream_data['stream_url']
    mime = stream_data.get('mime', 'audio/mp4')

    # Forward range header if browser sent one (for seeking)
    range_header = request.headers.get('Range')
    req_headers = {
        **HEADERS,
        'Referer': 'https://www.youtube.com/',
        'Origin': 'https://www.youtube.com',
    }
    if range_header:
        req_headers['Range'] = range_header

    try:
        yt_resp = requests.get(
            stream_url,
            headers=req_headers,
            stream=True,
            timeout=30,
        )

        status = yt_resp.status_code  # usually 200 or 206

        def generate():
            for chunk in yt_resp.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        resp_headers = {
            'Content-Type': mime,
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'no-cache',
        }

        # Forward content-range and content-length if present
        for h in ('Content-Length', 'Content-Range'):
            if h in yt_resp.headers:
                resp_headers[h] = yt_resp.headers[h]

        return Response(
            stream_with_context(generate()),
            status=status,
            headers=resp_headers,
            mimetype=mime,
        )

    except Exception as ex:
        print(f'PROXY ERROR [{video_id}]: {ex}')
        # Cache expired — try fresh extraction
        cache.pop(ck, None)
        result, err = extract_stream(video_id)
        if err or not result:
            return 'Proxy failed', 503
        cache_set(ck, result)
        # Redirect to retry
        return proxy_audio(video_id)


@app.route('/api/trending')
def trending():
    genre = request.args.get('genre', 'music hits 2025')
    ck = f'trending:{genre}'
    cached = cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
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