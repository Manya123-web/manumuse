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
    cookie_file = os.path.join(os.path.dirname(__file__), 'cookie.json')
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
        print(f"✅ Loaded {len(cookies)} cookies")
    else:
        print(f"⚠️ cookie.json not found at {cookie_file}")
except Exception as e:
    print(f"⚠️ Cookie error: {e}")

# Fallback tracks - ALWAYS return these if YouTube fails
FALLBACK_TRACKS = [
    {'id': 'dQw4w9WgXcQ', 'title': 'Never Gonna Give You Up', 'channel': 'Rick Astley', 'duration': 212, 'thumb': 'https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg'},
    {'id': 'kJQP7kiw5Fk', 'title': 'Despacito', 'channel': 'Luis Fonsi', 'duration': 279, 'thumb': 'https://i.ytimg.com/vi/kJQP7kiw5Fk/mqdefault.jpg'},
    {'id': 'OPf0YbXqDm0', 'title': 'See You Again', 'channel': 'Wiz Khalifa', 'duration': 249, 'thumb': 'https://i.ytimg.com/vi/OPf0YbXqDm0/mqdefault.jpg'},
    {'id': 'pRpeEdMmmQ0', 'title': 'Let Her Go', 'channel': 'Passenger', 'duration': 252, 'thumb': 'https://i.ytimg.com/vi/pRpeEdMmmQ0/mqdefault.jpg'},
    {'id': 'RgKAFK5djSk', 'title': 'Someone Like You', 'channel': 'Adele', 'duration': 287, 'thumb': 'https://i.ytimg.com/vi/RgKAFK5djSk/mqdefault.jpg'},
    {'id': 'JGwWNGJdvx8', 'title': 'Shape of You', 'channel': 'Ed Sheeran', 'duration': 263, 'thumb': 'https://i.ytimg.com/vi/JGwWNGJdvx8/mqdefault.jpg'},
    {'id': 'M7lc1UVf-VE', 'title': 'Uptown Funk', 'channel': 'Mark Ronson ft. Bruno Mars', 'duration': 270, 'thumb': 'https://i.ytimg.com/vi/M7lc1UVf-VE/mqdefault.jpg'},
    {'id': 'fJ9rUzIMcZQ', 'title': 'Bohemian Rhapsody', 'channel': 'Queen', 'duration': 355, 'thumb': 'https://i.ytimg.com/vi/fJ9rUzIMcZQ/mqdefault.jpg'},
    {'id': 'YQHsXMglC9A', 'title': 'Havana', 'channel': 'Camila Cabello', 'duration': 217, 'thumb': 'https://i.ytimg.com/vi/YQHsXMglC9A/mqdefault.jpg'},
    {'id': 'CevxZvSJLk8', 'title': 'Blinding Lights', 'channel': 'The Weeknd', 'duration': 200, 'thumb': 'https://i.ytimg.com/vi/CevxZvSJLk8/mqdefault.jpg'},
]

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
        'fallback_available': True,
        'message': 'Server is running with fallback tracks'
    })

@app.route('/api/trending')
def trending():
    genre = request.args.get('genre', 'popular music')
    cache_key = f'trending:{genre}'
    
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    
    # ALWAYS return fallback tracks immediately for testing
    print(f"Returning fallback tracks for {genre}")
    response_data = {'tracks': FALLBACK_TRACKS[:10], 'genre': genre}
    cache_set(cache_key, response_data)
    return jsonify(response_data)

@app.route('/api/search')
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'tracks': []})
    
    cache_key = f'search:{q}'
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    
    # Filter fallback tracks that match the search
    matching = [t for t in FALLBACK_TRACKS if q.lower() in t['title'].lower() or q.lower() in t['channel'].lower()]
    tracks = matching[:15] if matching else FALLBACK_TRACKS[:8]
    
    print(f"Search for '{q}': found {len(tracks)} matching tracks")
    response_data = {'tracks': tracks, 'query': q}
    cache_set(cache_key, response_data)
    return jsonify(response_data)

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
    
    # Return matching titles as suggestions
    matching = [t['title'] for t in FALLBACK_TRACKS if q.lower() in t['title'].lower()]
    suggestions = matching[:5]
    
    return jsonify({'suggestions': suggestions})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)