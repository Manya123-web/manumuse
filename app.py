import os
import time
import re
import requests
import json
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import random

app = Flask(__name__, static_folder='static')
CORS(app)

# ─── Configuration ────────────────────────────────────────────────────────────
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

# ─── STRATEGY 1: Piped API (Better than Invidious) ──────────────────────────
PIPED_INSTANCES = [
    'https://pipedapi.kavin.rocks',
    'https://pipedapi.moomoo.me',
    'https://pipedapi.adminforge.de',
    'https://pipedapi.lunar.icu',
]

def get_working_piped_instance():
    """Find working Piped instance"""
    cached = cache_get('piped_instance')
    if cached:
        return cached
    
    for instance in PIPED_INSTANCES:
        try:
            response = requests.get(f"{instance}/healthcheck", timeout=5)
            if response.status_code == 200:
                cache_set('piped_instance', instance)
                print(f"✅ Using Piped instance: {instance}")
                return instance
        except:
            continue
    
    return PIPED_INSTANCES[0]

def search_piped(query, limit=20):
    """Search using Piped API"""
    instance = get_working_piped_instance()
    
    try:
        # Piped search endpoint
        search_url = f"{instance}/search"
        params = {
            'q': query,
            'filter': 'videos',
            'page': 1
        }
        
        response = requests.get(search_url, params=params, timeout=10)
        
        if response.status_code != 200:
            return []
        
        data = response.json()
        tracks = []
        
        for item in data.get('items', [])[:limit]:
            if item.get('type') == 'video':
                video_id = item.get('url', '').split('watch?v=')[-1]
                if video_id:
                    tracks.append({
                        'id': video_id,
                        'title': item.get('title', 'Unknown'),
                        'channel': item.get('uploaderName', 'Unknown'),
                        'duration': item.get('duration', 0),
                        'thumb': item.get('thumbnail', f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"),
                    })
        
        return tracks
        
    except Exception as e:
        print(f"Piped search error: {e}")
        return []

def get_stream_piped(video_id):
    """Get audio stream from Piped API"""
    instance = get_working_piped_instance()
    
    try:
        # Get stream info from Piped
        stream_url = f"{instance}/streams/{video_id}"
        response = requests.get(stream_url, timeout=10)
        
        if response.status_code != 200:
            return None, f"Stream fetch failed: {response.status_code}"
        
        data = response.json()
        
        # Get audio streams
        audio_streams = data.get('audioStreams', [])
        
        if not audio_streams:
            return None, "No audio streams found"
        
        # Get best quality audio
        best_audio = audio_streams[-1]  # Usually last is highest quality
        
        return {
            'stream_url': best_audio.get('url'),
            'mime': best_audio.get('mimeType', 'audio/mp4'),
            'duration': data.get('duration', 0),
            'title': data.get('title', 'Unknown'),
            'channel': data.get('uploader', 'Unknown'),
        }, None
        
    except Exception as e:
        print(f"Piped stream error: {e}")
        return None, str(e)

# ─── STRATEGY 2: yt-dlp with Cookies (if available) ──────────────────────────
def extract_stream_ytdlp(video_id):
    """Fallback to yt-dlp"""
    try:
        import yt_dlp
        
        yt_url = f'https://www.youtube.com/watch?v={video_id}'
        
        # Try multiple client strategies
        strategies = [
            {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'skip_download': True,
                'noplaylist': True,
                'extractor_args': {'youtube': {'player_client': ['android']}},
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36',
                },
            },
            {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'skip_download': True,
                'extractor_args': {'youtube': {'player_client': ['ios']}},
            }
        ]
        
        for opts in strategies:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(yt_url, download=False)
                    
                if info and info.get('url'):
                    return {
                        'stream_url': info.get('url'),
                        'mime': 'audio/mp4',
                        'duration': info.get('duration', 0),
                        'title': info.get('title', 'Unknown'),
                        'channel': info.get('uploader', 'Unknown'),
                    }, None
            except:
                continue
                
    except Exception as e:
        print(f"yt-dlp error: {e}")
    
    return None, "All extraction methods failed"

# ─── MAIN EXTRACTION FUNCTION ────────────────────────────────────────────────
def extract_stream(video_id):
    """Try multiple strategies in order"""
    
    # Strategy 1: Piped API (Most reliable for cloud)
    print(f"🎵 Trying Piped for {video_id}")
    result, error = get_stream_piped(video_id)
    if result:
        print(f"✅ Piped success for {video_id}")
        return result, None
    print(f"❌ Piped failed: {error}")
    
    # Strategy 2: yt-dlp (if Piped fails)
    print(f"🎵 Trying yt-dlp for {video_id}")
    result, error = extract_stream_ytdlp(video_id)
    if result:
        print(f"✅ yt-dlp success for {video_id}")
        return result, None
    print(f"❌ yt-dlp failed: {error}")
    
    return None, "All strategies failed"

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
    piped = get_working_piped_instance()
    return jsonify({
        'status': 'ok',
        'version': '6.1',
        'server': 'flask-piped',
        'piped_instance': piped,
        'timestamp': time.time()
    })

@app.route('/api/search')
def search():
    q = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 20)), 40)
    
    if not q:
        return jsonify({'error': 'No query', 'tracks': []}), 400
    
    cache_key = f'search:{q}:{limit}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    
    # Use Piped for search
    tracks = search_piped(q, limit)
    
    if not tracks:
        tracks = []
    
    data = {'tracks': tracks, 'query': q}
    cache_set(cache_key, data)
    return jsonify(data)

@app.route('/api/stream/<video_id>')
def stream_info(video_id):
    """Get stream info"""
    if not re.match(r'^[a-zA-Z0-9_\-]{6,15}$', video_id):
        return jsonify({'error': 'Invalid video ID'}), 400
    
    cache_key = f'streaminfo:{video_id}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify({**cached, 'url': f'/api/proxy/{video_id}'})
    
    # Extract stream using multiple strategies
    result, error = extract_stream(video_id)
    
    if not result:
        return jsonify({'error': error or 'Could not extract stream'}), 404
    
    cache_set(cache_key, result)
    
    return jsonify({
        'url': f'/api/proxy/{video_id}',
        'mime': result['mime'],
        'duration': result['duration'],
        'title': result['title'],
        'channel': result['channel'],
        'thumb': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        'video_id': video_id,
    })

@app.route('/api/proxy/<video_id>')
def proxy_audio(video_id):
    """Proxy audio stream"""
    if not re.match(r'^[a-zA-Z0-9_\-]{6,15}$', video_id):
        return 'Invalid ID', 400
    
    cache_key = f'streaminfo:{video_id}'
    stream_data = cache_get(cache_key)
    
    if not stream_data:
        result, error = extract_stream(video_id)
        if not result:
            return f'Stream unavailable: {error}', 503
        cache_set(cache_key, result)
        stream_data = result
    
    stream_url = stream_data['stream_url']
    mime = stream_data.get('mime', 'audio/mp4')
    
    if not stream_url:
        return 'No stream URL', 404
    
    # Forward range header for seeking
    range_header = request.headers.get('Range')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.youtube.com/',
        'Accept': '*/*',
    }
    if range_header:
        headers['Range'] = range_header
    
    try:
        yt_resp = requests.get(stream_url, headers=headers, stream=True, timeout=30)
        
        if yt_resp.status_code not in [200, 206]:
            print(f"Proxy error: status {yt_resp.status_code} for {video_id}")
            # Clear cache and retry once
            cache_set(cache_key, None)
            result, error = extract_stream(video_id)
            if result:
                cache_set(cache_key, result)
                return proxy_audio(video_id)
            return f'Stream error: {yt_resp.status_code}', 503
        
        def generate():
            for chunk in yt_resp.iter_content(chunk_size=16384):
                if chunk:
                    yield chunk
        
        resp_headers = {
            'Content-Type': mime,
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'public, max-age=300',
            'Access-Control-Allow-Origin': '*',
        }
        
        for h in ('Content-Length', 'Content-Range'):
            if h in yt_resp.headers:
                resp_headers[h] = yt_resp.headers[h]
        
        return Response(
            stream_with_context(generate()),
            status=yt_resp.status_code,
            headers=resp_headers,
            mimetype=mime,
        )
        
    except Exception as ex:
        print(f'Proxy error for {video_id}: {ex}')
        return 'Proxy failed', 503

@app.route('/api/trending')
def trending():
    genre = request.args.get('genre', 'music hits 2025')
    cache_key = f'trending:{genre}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    
    tracks = search_piped(genre, 25)
    data = {'tracks': tracks, 'genre': genre}
    cache_set(cache_key, data)
    return jsonify(data)

@app.route('/api/suggestions')
def suggestions():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'suggestions': []})
    
    cache_key = f'suggest:{q}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    
    tracks = search_piped(q, 5)
    suggestions = [track['title'] for track in tracks[:5]]
    
    data = {'suggestions': suggestions}
    cache_set(cache_key, data)
    return jsonify(data)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)