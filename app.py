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
# List of public Invidious instances (regularly updated list)
INVIDIOUS_INSTANCES = [
    'https://invidious.io.lol',
    'https://yewtu.be',
    'https://invidious.privacydev.net',
    'https://inv.riverside.rocks',
    'https://invidious.flokinet.to',
    'https://invidious.snopyta.org',
    'https://inv.vern.cc',
    'https://invidious.kavin.rocks',
    'https://vid.puffyan.us',
    'https://inv.us.projectsegfault.com',
]

# Cache for performance
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
    """Find a working Invidious instance"""
    # Check cache first
    cached_instance = cache_get('working_instance')
    if cached_instance:
        return cached_instance
    
    # Test instances
    for instance in INVIDIOUS_INSTANCES:
        try:
            response = requests.get(f"{instance}/api/v1/stats", timeout=5)
            if response.status_code == 200:
                cache_set('working_instance', instance)
                print(f"✅ Using Invidious instance: {instance}")
                return instance
        except:
            continue
    
    # Fallback to a known reliable one
    return 'https://yewtu.be'

def parse_duration(duration_seconds):
    """Convert seconds to readable duration"""
    if not duration_seconds:
        return 0
    return int(duration_seconds)

def parse_track_from_invidious(video_data):
    """Parse track data from Invidious API response"""
    try:
        # Get best thumbnail
        thumbnails = video_data.get('videoThumbnails', [])
        thumb = thumbnails[-1]['url'] if thumbnails else f"https://i.ytimg.com/vi/{video_data.get('videoId', '')}/mqdefault.jpg"
        
        return {
            'id': video_data.get('videoId', ''),
            'title': video_data.get('title', 'Unknown'),
            'channel': video_data.get('author', video_data.get('authorId', 'Unknown')),
            'duration': parse_duration(video_data.get('lengthSeconds', 0)),
            'thumb': thumb,
        }
    except Exception as e:
        print(f"Error parsing track: {e}")
        return None

def search_invidious(query, limit=20):
    """Search for tracks using Invidious API"""
    instance = get_working_invidious_instance()
    
    try:
        # Invidious search API
        search_url = f"{instance}/api/v1/search"
        params = {
            'q': query,
            'type': 'video',
            'sort_by': 'relevance',
            'page': 1
        }
        
        response = requests.get(search_url, params=params, timeout=15)
        
        if response.status_code != 200:
            print(f"Invidious search failed: {response.status_code}")
            return []
        
        data = response.json()
        
        # Filter and parse results
        tracks = []
        for item in data[:limit]:
            # Only include videos (not channels or playlists)
            if item.get('type') == 'video' and item.get('videoId'):
                track = parse_track_from_invidious(item)
                if track:
                    tracks.append(track)
        
        return tracks
        
    except Exception as e:
        print(f"Search error: {e}")
        return []

def get_audio_stream_from_invidious(video_id):
    """Get audio stream URL from Invidious"""
    instance = get_working_invidious_instance()
    
    try:
        # Get video info from Invidious
        video_url = f"{instance}/api/v1/videos/{video_id}"
        response = requests.get(video_url, timeout=15)
        
        if response.status_code != 200:
            print(f"Failed to get video info: {response.status_code}")
            return None, f"Video info fetch failed: {response.status_code}"
        
        data = response.json()
        
        # Get audio streams
        format_streams = data.get('formatStreams', [])
        adaptive_formats = data.get('adaptiveFormats', [])
        
        # Prefer audio-only streams
        audio_stream = None
        
        # Check adaptiveFormats first (usually better quality)
        for fmt in adaptive_formats:
            if fmt.get('type', '').startswith('audio/'):
                audio_stream = fmt
                break
        
        # If no audio-only, check formatStreams
        if not audio_stream:
            for fmt in format_streams:
                if fmt.get('type', '').startswith('audio/'):
                    audio_stream = fmt
                    break
        
        if not audio_stream:
            return None, "No audio stream found"
        
        # Get the stream URL
        stream_url = audio_stream.get('url')
        if not stream_url:
            return None, "No stream URL found"
        
        # Add CORS headers to URL (some instances need this)
        if not stream_url.startswith('http'):
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
        
    except requests.exceptions.Timeout:
        return None, "Request timeout"
    except Exception as e:
        print(f"Stream extraction error: {e}")
        return None, str(e)

# Fallback to yt-dlp if Invidious fails
def extract_stream_fallback(video_id):
    """Fallback to yt-dlp if Invidious fails"""
    try:
        import yt_dlp
        
        yt_url = f'https://www.youtube.com/watch?v={video_id}'
        
        opts = {
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
        }
        
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
            
    except Exception as e:
        print(f"Fallback extraction failed: {e}")
    
    return None, "All extraction methods failed"

# ─── Routes (Updated to use Invidious) ───────────────────────────────────────

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
        'invidious_instance': instance
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
    
    # Search using Invidious
    tracks = search_invidious(q, limit)
    
    if not tracks:
        # If Invidious fails, try yt-dlp as fallback
        try:
            import yt_dlp
            flat_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'skip_download': True,
            }
            with yt_dlp.YoutubeDL(flat_opts) as ydl:
                results = ydl.extract_info(f'ytsearch{limit}:{q}', download=False)
            
            for entry in results.get('entries', []):
                if entry and entry.get('id'):
                    tracks.append({
                        'id': entry['id'],
                        'title': entry.get('title', 'Unknown'),
                        'channel': entry.get('uploader', 'Unknown'),
                        'duration': entry.get('duration', 0),
                        'thumb': f"https://i.ytimg.com/vi/{entry['id']}/mqdefault.jpg",
                    })
        except Exception as e:
            print(f"Fallback search failed: {e}")
    
    data = {'tracks': tracks, 'query': q}
    cache_set(cache_key, data)
    return jsonify(data)

@app.route('/api/stream/<video_id>')
def stream_info(video_id):
    """Get stream info using Invidious"""
    if not re.match(r'^[a-zA-Z0-9_\-]{6,15}$', video_id):
        return jsonify({'error': 'Invalid video ID'}), 400
    
    cache_key = f'streaminfo:{video_id}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify({**cached, 'url': f'/api/proxy/{video_id}'})
    
    # Try Invidious first
    result, error = get_audio_stream_from_invidious(video_id)
    
    # If Invidious fails, try yt-dlp fallback
    if not result:
        print(f"Invidious failed for {video_id}, trying yt-dlp fallback")
        result, error = extract_stream_fallback(video_id)
    
    if not result:
        return jsonify({'error': error or 'Could not extract stream'}), 500
    
    cache_set(cache_key, result)
    
    return jsonify({
        'url': f'/api/proxy/{video_id}',
        'mime': result['mime'],
        'duration': result['duration'],
        'title': result['title'],
        'channel': result['channel'],
        'thumb': f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
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
        # Try to get stream data again
        result, error = get_audio_stream_from_invidious(video_id)
        if not result:
            result, error = extract_stream_fallback(video_id)
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
    }
    if range_header:
        headers['Range'] = range_header
    
    try:
        yt_resp = requests.get(stream_url, headers=headers, stream=True, timeout=30)
        
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
    
    # Get search results for suggestions
    tracks = search_invidious(q, 5)
    suggestions = [track['title'] for track in tracks[:5]]
    
    data = {'suggestions': suggestions}
    cache_set(cache_key, data)
    return jsonify(data)

@app.route('/api/instances')
def list_instances():
    """List available Invidious instances for debugging"""
    return jsonify({
        'instances': INVIDIOUS_INSTANCES,
        'current': get_working_invidious_instance()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)