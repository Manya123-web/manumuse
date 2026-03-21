import os
import time
import re
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__, static_folder='static')
CORS(app)

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

# Load cookies
cookies = None
try:
    cookie_file = 'cookie.json'
    if os.path.exists(cookie_file):
        with open(cookie_file, 'r') as f:
            data = json.load(f)
            if isinstance(data, list):
                cookies = {}
                for cookie in data:
                    if cookie.get('name') and cookie.get('value'):
                        cookies[cookie['name']] = cookie['value']
            else:
                cookies = data
        print(f"✅ Loaded cookies from {cookie_file}")
except Exception as e:
    print(f"⚠️ Cookie error: {e}")

# Fallback tracks (in case YouTube blocks requests)
FALLBACK_TRACKS = [
    {'id': 'dQw4w9WgXcQ', 'title': 'Never Gonna Give You Up', 'channel': 'Rick Astley', 'duration': 212},
    {'id': 'kJQP7kiw5Fk', 'title': 'Despacito', 'channel': 'Luis Fonsi', 'duration': 279},
    {'id': 'OPf0YbXqDm0', 'title': 'See You Again', 'channel': 'Wiz Khalifa', 'duration': 249},
    {'id': 'pRpeEdMmmQ0', 'title': 'Let Her Go', 'channel': 'Passenger', 'duration': 252},
    {'id': 'RgKAFK5djSk', 'title': 'Someone Like You', 'channel': 'Adele', 'duration': 287},
    {'id': 'JGwWNGJdvx8', 'title': 'Shape of You', 'channel': 'Ed Sheeran', 'duration': 263},
]

# Add thumbnails to fallback tracks
for track in FALLBACK_TRACKS:
    track['thumb'] = f"https://i.ytimg.com/vi/{track['id']}/mqdefault.jpg"

def get_ydl_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'socket_timeout': 30,
        'retries': 3,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
    }
    if cookies:
        opts['cookies'] = cookies
    return opts

def make_track(entry):
    if not entry or not entry.get('id'):
        return None
    return {
        'id': entry['id'],
        'title': entry.get('title', 'Unknown')[:100],
        'channel': entry.get('uploader') or entry.get('channel', 'Unknown'),
        'duration': entry.get('duration', 0),
        'thumb': f"https://i.ytimg.com/vi/{entry['id']}/mqdefault.jpg",
    }

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'cookies_loaded': cookies is not None,
        'cookies_count': len(cookies) if cookies else 0,
        'timestamp': time.time()
    })

@app.route('/api/trending')
def trending():
    genre = request.args.get('genre', 'popular music')
    cache_key = f'trending:{genre}'
    
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    
    try:
        # Try to fetch from YouTube
        search_query = f"ytsearch10:{genre}"
        print(f"Searching: {search_query}")
        
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            results = ydl.extract_info(search_query, download=False)
        
        tracks = []
        if results and results.get('entries'):
            for entry in results['entries']:
                track = make_track(entry)
                if track:
                    tracks.append(track)
        
        # If no tracks found, use fallback
        if not tracks:
            print("No tracks from YouTube, using fallback")
            tracks = FALLBACK_TRACKS[:10]
        
        response_data = {'tracks': tracks, 'genre': genre}
        cache_set(cache_key, response_data)
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Trending error: {e}")
        # Return fallback tracks on error
        return jsonify({'tracks': FALLBACK_TRACKS[:10], 'genre': genre, 'error': str(e)})

@app.route('/api/search')
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'tracks': []})
    
    cache_key = f'search:{q}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    
    try:
        search_query = f"ytsearch20:{q}"
        print(f"Searching: {search_query}")
        
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            results = ydl.extract_info(search_query, download=False)
        
        tracks = []
        if results and results.get('entries'):
            for entry in results['entries']:
                track = make_track(entry)
                if track:
                    tracks.append(track)
        
        # If no tracks found, return filtered fallback
        if not tracks:
            # Filter fallback tracks that match the search
            matching = [t for t in FALLBACK_TRACKS if q.lower() in t['title'].lower()]
            tracks = matching[:10] if matching else FALLBACK_TRACKS[:5]
        
        response_data = {'tracks': tracks, 'query': q}
        cache_set(cache_key, response_data)
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Search error: {e}")
        return jsonify({'tracks': FALLBACK_TRACKS[:5], 'query': q, 'error': str(e)})

@app.route('/api/stream/<video_id>')
def stream_url(video_id):
    try:
        yt_url = f'https://www.youtube.com/watch?v={video_id}'
        
        opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio/best',
            'skip_download': True,
            'nocheckcertificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
        }
        
        if cookies:
            opts['cookies'] = cookies
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(yt_url, download=False)
            
            # Get audio URL
            audio_url = None
            
            if info.get('url'):
                audio_url = info['url']
            elif info.get('formats'):
                for f in info['formats']:
                    if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                        if f.get('url'):
                            audio_url = f['url']
                            break
            
            if audio_url:
                return jsonify({
                    'url': audio_url,
                    'title': info.get('title', 'Unknown'),
                    'channel': info.get('uploader', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'thumb': f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                })
            else:
                return jsonify({'error': 'No audio stream'}), 404
                
    except Exception as e:
        print(f"Stream error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/suggestions')
def suggestions():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'suggestions': []})
    
    try:
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            results = ydl.extract_info(f"ytsearch3:{q}", download=False)
        
        suggestions = []
        if results and results.get('entries'):
            for entry in results['entries'][:5]:
                if entry and entry.get('title'):
                    suggestions.append(entry['title'])
        
        return jsonify({'suggestions': suggestions})
    except:
        return jsonify({'suggestions': []})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)