import os
import time
import re
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__, static_folder='static')
CORS(app)

# Simple cache
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
        print(f"✅ Loaded cookies")
except Exception as e:
    print(f"Cookie error: {e}")

# yt-dlp config - SIMPLIFIED for reliability
def get_ydl_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'force_generic_extractor': False,
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'no_color': True,
        'geo_bypass': True,
        'socket_timeout': 30,
        'retries': 3,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
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

@app.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'cookies_loaded': cookies is not None,
        'ytdlp_available': True
    })

@app.route('/api/trending')
def trending():
    genre = request.args.get('genre', 'popular music')
    cache_key = f'trending:{genre}'
    
    cached = cache_get(cache_key)
    if cached:
        return jsonify(cached)
    
    try:
        # Try multiple search terms
        search_terms = [genre, f"{genre} songs", f"top {genre}"]
        tracks = []
        
        for term in search_terms[:2]:  # Try first 2 terms
            if tracks:
                break
                
            search_query = f"ytsearch10:{term}"
            print(f"Searching: {search_query}")
            
            with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
                try:
                    results = ydl.extract_info(search_query, download=False)
                    if results and results.get('entries'):
                        for entry in results['entries']:
                            track = make_track(entry)
                            if track:
                                tracks.append(track)
                        if tracks:
                            print(f"Found {len(tracks)} tracks for {term}")
                            break
                except Exception as e:
                    print(f"Search failed for {term}: {e}")
                    continue
        
        # If still no tracks, use fallback
        if not tracks:
            fallback_tracks = [
                {'id': 'dQw4w9WgXcQ', 'title': 'Never Gonna Give You Up', 'channel': 'Rick Astley', 'duration': 212},
                {'id': 'kJQP7kiw5Fk', 'title': 'Despacito', 'channel': 'Luis Fonsi', 'duration': 279},
                {'id': 'OPf0YbXqDm0', 'title': 'See You Again', 'channel': 'Wiz Khalifa', 'duration': 249},
                {'id': 'pRpeEdMmmQ0', 'title': 'Let Her Go', 'channel': 'Passenger', 'duration': 252},
            ]
            for ft in fallback_tracks:
                ft['thumb'] = f"https://i.ytimg.com/vi/{ft['id']}/mqdefault.jpg"
            tracks = fallback_tracks
            print("Using fallback tracks")
        
        response_data = {'tracks': tracks, 'genre': genre}
        cache_set(cache_key, response_data)
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Trending error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'tracks': [], 'error': str(e)}), 500

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
        
        print(f"Found {len(tracks)} tracks")
        
        response_data = {'tracks': tracks, 'query': q}
        cache_set(cache_key, response_data)
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Search error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'tracks': [], 'error': str(e)}), 500

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
            
            # Try to get direct URL first
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