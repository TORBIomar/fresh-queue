"""Local desktop companion. Run with Python 3.10 or newer."""
import argparse
import json
import re
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from core import Store, ShuffleBag, DeliveryError, enqueue
from spotify import Spotify, playlist_id

ROOT = Path(__file__).resolve().parent
ORIGIN = 'http://127.0.0.1:5173'


class Companion:
    def __init__(self, state_path, client_id=''):
        self.store = Store(state_path)
        self.store.data.setdefault('client_id', client_id)
        self.spotify = Spotify(self.store, ORIGIN + '/callback')
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.RLock()

    def bag(self):
        profile = self.store.data.get('profile', {})
        playlist = self.store.data.get('playlist')
        if not playlist or playlist.get('account') != profile.get('id'):
            raise ValueError('Load one of your playlists first.')
        return ShuffleBag(self.store, profile['id'], playlist['id'], playlist['tracks'])

    def status(self):
        data = self.store.data
        profile = data.get('profile')
        result = {'client_id': data.get('client_id', ''), 'csrf': self.csrf,
                  'connected': bool(data.get('auth') and profile), 'profile': profile,
                  'playlist': None, 'redirect_uri': ORIGIN + '/callback'}
        playlist = data.get('playlist')
        if profile and playlist and playlist.get('account') == profile['id']:
            result['playlist'] = {'id': playlist['id'], 'name': playlist['name'], **self.bag().stats()}
        return result

    def load(self, value):
        ident = playlist_id(value)
        if not self.status()['connected']:
            raise ValueError('Connect to Spotify first.')
        playlist = self.spotify.playlist(ident)
        playlist['account'] = self.store.data['profile']['id']
        self.store.data['playlist'] = playlist
        self.bag()
        self.store.save()
        return self.status()

    def player(self):
        playback = self.spotify.request('GET', '/me/player') or {}
        device = playback.get('device') or {}
        return {'name': device.get('name'), 'id': device.get('id'),
                'is_restricted': device.get('is_restricted', False)}

    def queue(self, count, avoid_recent):
        if type(count) is not int or not 1 <= count <= 25:
            raise ValueError('Choose between 1 and 25 songs.')
        bag = self.bag()
        device = self.player()
        if not device.get('id') or device.get('is_restricted'):
            raise ValueError('Start a song in Spotify on your iPhone or desktop, then try again. This player must allow remote control.')
        current = self.spotify.request('GET', '/me/player/queue') or {}
        excluded = {t['uri'] for t in current.get('queue', []) if t and t.get('uri')}
        playing = current.get('currently_playing')
        if playing and playing.get('uri'):
            excluded.add(playing['uri'])
        if avoid_recent:
            recent = self.spotify.request('GET', '/me/player/recently-played?limit=50') or {}
            for row in recent.get('items', []):
                item = row.get('track') or row.get('item')
                if item and item.get('uri'):
                    excluded.add(item['uri'])
        selected = bag.choose(count, excluded)
        result = enqueue(bag, selected, lambda uri: self.spotify.add(uri, device['id']))
        result['device'] = device['name']
        result['state'] = self.status()
        result['eligible'] = len(bag.choose(bag.total, excluded))
        return result


def make_server(companion, port=5173):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # OAuth codes and playlist links do not belong in logs.

        def send(self, status, body, content_type='application/json; charset=utf-8', location=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            if location:
                self.send_header('Location', location)
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, mutate=False):
            expected = '127.0.0.1:' + str(self.server.server_port)
            origin = self.headers.get('Origin')
            if self.headers.get('Host') != expected or (origin and origin != 'http://' + expected):
                return False
            if mutate:
                return secrets.compare_digest(self.headers.get('X-Fresh-Queue', ''), companion.csrf)
            return True

        def do_GET(self):
            if not self.allowed():
                return self.send(403, {'error': 'Open this app using its 127.0.0.1 address.'})
            parsed = urlparse(self.path)
            try:
                with companion.lock:
                    if parsed.path == '/callback':
                        query = parse_qs(parsed.query)
                        companion.spotify.callback(query.get('state', [''])[0], query.get('code', [''])[0])
                        return self.send(303, b'', location='/')
                    if parsed.path == '/api/state':
                        return self.send(200, companion.status())
                files = {'/': ('index.html', 'text/html; charset=utf-8'),
                         '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                         '/style.css': ('style.css', 'text/css; charset=utf-8')}
                if parsed.path in files:
                    name, content_type = files[parsed.path]
                    return self.send(200, (ROOT / 'static' / name).read_bytes(), content_type)
                if parsed.path == '/favicon.ico':
                    return self.send(204, b'')
                self.send(404, {'error': 'Page not found.'})
            except (ValueError, DeliveryError) as exc:
                if parsed.path == '/callback':
                    # Static error page avoids rendering anything supplied by the callback.
                    return self.send(400, '<!doctype html><meta charset="utf-8"><title>Spotify connection</title><p>Spotify sign-in failed or expired.</p><p>Check that the Redirect URI is http://127.0.0.1:5173/callback and your account is in Users Management.</p><a href="/">Return to Fresh Queue and connect again</a>', 'text/html; charset=utf-8')
                self.send(400, {'error': str(exc)})

        def do_POST(self):
            if not self.allowed(mutate=True):
                return self.send(403, {'error': 'Refresh this page and try again.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('Invalid request.')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Invalid request.')
                with companion.lock:
                    if self.path == '/api/connect':
                        client = body.get('client_id', '').strip()
                        if not re.fullmatch(r'[a-fA-F0-9]{32}', client):
                            raise ValueError('Enter the 32-character Client ID from your Spotify developer app.')
                        if client != companion.store.data.get('client_id'):
                            companion.store.data.pop('auth', None)
                            companion.store.data.pop('profile', None)
                        companion.store.data['client_id'] = client
                        companion.store.save()
                        result = {'url': companion.spotify.authorize()}
                    elif self.path == '/api/load':
                        result = companion.load(body.get('playlist', ''))
                    elif self.path == '/api/player':
                        result = companion.player()
                    elif self.path == '/api/queue':
                        result = companion.queue(body.get('count'), body.get('avoid_recent') is not False)
                    elif self.path == '/api/reset':
                        companion.bag().reset()
                        result = companion.status()
                    elif self.path == '/api/disconnect':
                        for key in ('auth', 'profile'):
                            companion.store.data.pop(key, None)
                        companion.spotify.pending = None
                        companion.store.save()
                        result = companion.status()
                    else:
                        return self.send(404, {'error': 'Action not found.'})
                self.send(200, result)
            except (ValueError, TypeError, DeliveryError) as exc:
                self.send(400, {'error': str(exc)})
            except OSError:
                self.send(500, {'error': 'Could not save progress. Check free disk space and file permissions before continuing.'})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description='Fresh Queue for Spotify')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--state-dir', type=Path, default=ROOT / '.local')
    args = parser.parse_args()
    config = json.loads((ROOT / 'config.json').read_text())
    try:
        companion = Companion(args.state_dir / 'state.json', config.get('client_id', ''))
        server = make_server(companion)
    except (OSError, ValueError) as exc:
        raise SystemExit('Could not start Fresh Queue: ' + str(exc)) from exc
    print('Fresh Queue is running at ' + ORIGIN, flush=True)
    print('Keep this window open. Press Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        webbrowser.open(ORIGIN)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
