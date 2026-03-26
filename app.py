import os
import time
import re
import requests
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import random

app = Flask(__name__, static_folder='static')
CORS(app)

# ─── Configuration ────────────────────────────────────────────────────────────
# Updated list of working Invidious instances (as of 2025)
INVIDIOUS_INSTANCES = [
    'https://invidious.privacydev.net',
    'https://inv.vern.cc',
    'https://invidious.flokinet.to',
    'https://invidious.snopyta.org',
    'https://inv.bp.projectsegfau.lt',
    'https://invidious.kavin.rocks',
    'https://vid.puffyan.us',
    'https://yewtu.be',
    'https://invidious.tiekoetter.com',
    'https://invidious.projectsegfau.lt',
]

# Cache
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

def get_working_invidious_instance():
    """Find a working Invidious instance with caching"""
    # Check cache first
    cached_instance = cache_get('working_instance')
    if cached_instance:
        return cached_instance
    
    # Test instances
    working_instances = []
    for instance in INVIDIOUS_INSTANCES:
        try:
            # Test with a known video ID (Rick Astley - Never Gonna Give You Up)
            test_url = f"{instance}/api/v1/videos/dQw4w9WgXcQ"
            response = requests.get(test_url, timeout=5)
            if response.status_code == 200:
                working_instances.append(instance)
                print(f"✅ Working instance: {instance}")
        except:
            continue
    
    if working_instances:
        # Cache for 5 minutes
        selected = random.choice(working_instances)
        cache_set('working_instance', selected)
        return selected
    
    # Fallback to a known reliable instance
    return 'https://invidious.privacydev.net'

def search_invidious(query, limit=20):
    """Search for tracks using Invidious API with retry"""
    instance = get_working_invidious_instance()
    
    try:
        search_url = f"{instance}/api/v1/search"
        params = {
            'q': query,
            'type': 'video',
            'sort_by': 'relevance',
            'page': 1
        }
        
        response = requests.get(search_url, params=params, timeout=10)
        
        if response.status_code != 200:
            print(f"Invidious search failed: {response.status_code}")
            return []
        
        data = response.json()
        tracks = []
        
        for item in data[:limit]:
            if item.get('type') == 'video' and item.get('videoId'):
                # Get better thumbnail
                thumb = f"https://i.ytimg.com/vi/{item['videoId']}/hqdefault.jpg"
                
                tracks.append({
                    'id': item['videoId'],
                    'title': item.get('title', 'Unknown'),
                    'channel': item.get('author', 'Unknown'),
                    'duration': item.get('lengthSeconds', 0),
                    'thumb': thumb,
                })
        
        return tracks
        
    except Exception as e:
        print(f"Search error: {e}")
        return []

def get_audio_stream_from_invidious(video_id):
    """Get audio stream URL from Invidious with multiple fallbacks"""
    # Try multiple instances if first fails
    for instance in [get_working_invidious_instance()] + INVIDIOUS_INSTANCES[:3]:
        try:
            video_url = f"{instance}/api/v1/videos/{video_id}"
            response = requests.get(video_url, timeout=10)
            
            if response.status_code != 200:
                continue
            
            data = response.json()
            
            # Check for error messages
            if data.get('error'):
                print(f"Invidious error: {data['error']}")
                continue
            
            # Get audio streams
            format_streams = data.get('formatStreams', [])
            adaptive_formats = data.get('adaptiveFormats', [])
            
            # Find best audio stream
            audio_stream = None
            
            # First priority: audio-only streams
            for fmt in adaptive_formats + format_streams:
                if fmt.get('type', '').startswith('audio/'):
                    # Prefer higher quality
                    if not audio_stream or fmt.get('bitrate', 0) > audio_stream.get('bitrate', 0):
                        audio_stream = fmt
            
            if not audio_stream:
                continue
            
            # Get stream URL
            stream_url = audio_stream.get('url')
            if not stream_url:
                continue
            
            # Fix relative URLs
            if stream_url.startswith('/'):
                stream_url = f"{instance}{stream_url}"
            
            # Determine MIME type
            mime_type = audio_stream.get('type', 'audio/mp4').split(';')[0]
            
            return {
                'stream_url': stream_url,
                'mime': mime_type,
                'duration': data.get('lengthSeconds', 0),
                'title': data.get('title', 'Unknown'),
                'channel': data.get('author', 'Unknown'),
            }, None
            
        except Exception as e:
            print(f"Instance {instance} failed: {e}")
            continue
    
    return None, "All Invidious instances failed"

# ─── Routes ───────────────────────────────────────────────────────────────────

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
    instance = get_working_invidious_instance()
    return jsonify({
        'status': 'ok',
        'version': '6.0',
        'server': 'flask-invidious',
        'invidious_instance': instance,
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
    
    tracks = search_invidious(q, limit)
    
    if not tracks:
        # Return empty but not error
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
    
    # Get stream from Invidious
    result, error = get_audio_stream_from_invidious(video_id)
    
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
        result, error = get_audio_stream_from_invidious(video_id)
        if not result:
            return 'Stream unavailable', 503
        cache_set(cache_key, result)
        stream_data = result
    
    stream_url = stream_data['stream_url']
    mime = stream_data.get('mime', 'audio/mp4')
    
    # Forward range header for seeking
    range_header = request.headers.get('Range')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36',
        'Referer': 'https://www.youtube.com/',
        'Accept': '*/*',
    }
    if range_header:
        headers['Range'] = range_header
    
    try:
        yt_resp = requests.get(stream_url, headers=headers, stream=True, timeout=30)
        
        if yt_resp.status_code not in [200, 206]:
            print(f"Proxy error: status {yt_resp.status_code}")
            return 'Stream error', 503
        
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
        print(f'Proxy error: {ex}')
        return 'Proxy failed', 503

@app.route('/api/trending')
def trending():
    genre = request.args.get('genre', 'music hits 2025')
    cache_key = f'trending:{genre}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    
    tracks = search_invidious(genre, 25)
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
    
    tracks = search_invidious(q, 5)
    suggestions = [track['title'] for track in tracks[:5]]
    
    data = {'suggestions': suggestions}
    cache_set(cache_key, data)
    return jsonify(data)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)