"""Spotify Web API client using PKCE, without a client secret."""
import base64
import hashlib
import json
import re
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from core import DeliveryError

API = 'https://api.spotify.com/v1'
TOKEN = 'https://accounts.spotify.com/api/token'
SCOPES = 'playlist-read-private playlist-read-collaborative user-read-playback-state user-read-currently-playing user-modify-playback-state user-read-recently-played'


def http(method, url, headers, body):
    req = Request(url, data=body, headers=headers, method=method)
    with urlopen(req, timeout=20) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def playlist_id(value):
    value = value.strip()
    if value.startswith('spotify:playlist:'):
        value = value.removeprefix('spotify:playlist:')
    elif value.startswith('https://'):
        parsed = urlparse(value)
        if parsed.hostname != 'open.spotify.com':
            raise ValueError('Paste a Spotify playlist link, URI, or playlist ID.')
        match = re.fullmatch(r'/(?:intl-[a-z]+/)?playlist/([A-Za-z0-9]{22})/?', parsed.path)
        value = match[1] if match else ''
    if not re.fullmatch(r'[A-Za-z0-9]{22}', value):
        raise ValueError('Paste a Spotify playlist link, URI, or playlist ID.')
    return value


class Spotify:
    def __init__(self, store, redirect, transport=http):
        self.store, self.redirect, self.transport = store, redirect, transport
        self.pending = None

    def authorize(self):
        client = self.store.data.get('client_id', '')
        if not re.fullmatch(r'[a-fA-F0-9]{32}', client):
            raise ValueError('Enter your 32-character Spotify app Client ID.')
        verifier = secrets.token_urlsafe(64)
        self.pending = {'state': secrets.token_urlsafe(32), 'verifier': verifier, 'created': time.time()}
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        return 'https://accounts.spotify.com/authorize?' + urlencode({
            'client_id': client, 'response_type': 'code', 'redirect_uri': self.redirect,
            'scope': SCOPES, 'state': self.pending['state'],
            'code_challenge': challenge, 'code_challenge_method': 'S256'})

    def callback(self, state, code):
        if (not self.pending or not secrets.compare_digest(state, self.pending['state'])
                or time.time() - self.pending['created'] > 600):
            raise ValueError('This sign-in link expired or is invalid. Connect to Spotify again.')
        pending, self.pending = self.pending, None
        if not code:
            raise ValueError('Spotify sign-in was cancelled. You can connect again.')
        auth = self.token({'grant_type': 'authorization_code', 'code': code,
                           'redirect_uri': self.redirect, 'code_verifier': pending['verifier']})
        self.store.data['auth'] = auth
        self.store.data.pop('profile', None)
        self.store.save()
        profile = self.request('GET', '/me')
        self.store.data['profile'] = {'id': profile['id'], 'display_name': profile.get('display_name') or 'Spotify listener'}
        self.store.save()

    def token(self, data):
        data = {**data, 'client_id': self.store.data['client_id']}
        try:
            result = self.transport('POST', TOKEN, {'Content-Type': 'application/x-www-form-urlencoded'}, urlencode(data).encode())
        except HTTPError as exc:
            raise DeliveryError('Spotify could not sign you in. Check the Client ID and registered Redirect URI, then reconnect.') from exc
        except (OSError, URLError, ValueError) as exc:
            raise DeliveryError('Could not reach Spotify to sign in. Check your connection and reconnect.') from exc
        if not result or not result.get('access_token'):
            raise DeliveryError('Spotify returned no access token. Connect again.')
        return {**result, 'expires_at': time.time() + result.get('expires_in', 3600)}

    def refresh(self):
        old = self.store.data.get('auth', {})
        if not old.get('refresh_token'):
            raise DeliveryError('Connect to Spotify first.')
        new = self.token({'grant_type': 'refresh_token', 'refresh_token': old['refresh_token']})
        new.setdefault('refresh_token', old['refresh_token'])
        self.store.data['auth'] = new
        self.store.save()

    def request(self, method, path, retry_auth=True):
        auth = self.store.data.get('auth')
        if not auth:
            raise DeliveryError('Connect to Spotify first.')
        if auth.get('expires_at', 0) <= time.time() + 60:
            self.refresh()
        auth = self.store.data['auth']
        try:
            return self.transport(method, API + path, {'Authorization': 'Bearer ' + auth['access_token']}, None)
        except HTTPError as exc:
            # A 401 definitively rejected the request, so refreshing and retrying is safe.
            if exc.code == 401 and retry_auth:
                self.refresh()
                return self.request(method, path, retry_auth=False)
            messages = {
                401: 'Your Spotify connection expired. Connect again.',
                403: 'Spotify denied access. Check Premium, add your account under Users Management in the developer dashboard, and use a playlist you own or collaborate on.',
                404: 'Spotify could not find the playlist or an active player. Check the playlist link and start a song on your iPhone or desktop.',
                429: 'Spotify is limiting requests. Wait ' + str(exc.headers.get('Retry-After', 'a few')) + ' seconds before trying again.'}
            message = messages.get(exc.code, 'Spotify returned an error. Try again later.')
            raise DeliveryError(message, uncertain=method == 'POST' and exc.code >= 500) from exc
        except (OSError, URLError, ValueError) as exc:
            raise DeliveryError('Connection interrupted. Check Spotify and your internet connection.', uncertain=method == 'POST') from exc

    def playlist(self, ident):
        metadata = self.request('GET', '/playlists/' + ident)
        if 'items' not in metadata and 'tracks' not in metadata:
            raise DeliveryError('Spotify allows this app to read playlists you own or collaborate on. Copy this playlist into one of your own first.')
        tracks, offset = [], 0
        while True:
            page = self.request('GET', '/playlists/' + ident + '/items?' + urlencode({'limit': 50, 'offset': offset}))
            rows = page.get('items', [])
            for row in rows:
                item = row.get('item', row.get('track')) if row else None
                if item:
                    tracks.append({k: item[k] for k in ('uri', 'name', 'artists', 'type', 'is_local', 'is_playable') if k in item})
            if not page.get('next') or not rows:
                break
            offset += len(rows)
        return {'id': ident, 'name': metadata.get('name') or 'Your playlist', 'tracks': tracks}

    def add(self, uri, device_id):
        self.request('POST', '/me/player/queue?' + urlencode({'uri': uri, 'device_id': device_id}))
