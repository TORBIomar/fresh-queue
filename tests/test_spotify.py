import importlib
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from test_core import track


class SpotifyTests(unittest.TestCase):
    def setUp(self):
        try:
            self.m = importlib.import_module('spotify')
        except ImportError:
            self.fail('Spotify integration has not been implemented yet')
        from core import Store
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state.json')
        self.store.data['client_id'] = 'a' * 32
        self.store.data['auth'] = {'access_token': 'old-token', 'refresh_token': 'refresh', 'expires_at': 99999999999}

    def api(self, transport):
        return self.m.Spotify(self.store, 'http://127.0.0.1:5173/callback', transport)

    def test_authorization_uses_pkce_exact_redirect_and_no_secret(self):
        api = self.api(lambda *args: None)
        query = parse_qs(urlparse(api.authorize()).query)
        self.assertEqual(query['redirect_uri'], ['http://127.0.0.1:5173/callback'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertGreaterEqual(len(query['code_challenge'][0]), 43)
        self.assertNotIn('client_secret', query)
        self.assertIn('user-read-currently-playing', query['scope'][0].split())

    def test_wrong_or_expired_callback_state_never_exchanges_code(self):
        def transport(*args):
            self.fail('Invalid callback must not reach Spotify')
        api = self.api(transport)
        api.authorize()
        with self.assertRaises(ValueError):
            api.callback('wrong', 'code')
        api.pending['created'] = 0
        with self.assertRaises(ValueError):
            api.callback(api.pending['state'], 'code')

    def test_callback_and_refresh_keep_rotating_tokens_server_side(self):
        def transport(method, url, headers, body):
            if url.endswith('/api/token'):
                data = parse_qs(body.decode())
                self.assertNotIn('client_secret', data)
                if data['grant_type'] == ['authorization_code']:
                    self.assertIn('code_verifier', data)
                    return {'access_token': 'new', 'refresh_token': 'rotated', 'expires_in': 3600}
                self.assertEqual(data['refresh_token'], ['rotated'])
                return {'access_token': 'refreshed', 'expires_in': 3600}
            self.assertEqual(headers['Authorization'], 'Bearer new')
            return {'id': 'listener', 'display_name': 'Listener'}
        api = self.api(transport)
        state = parse_qs(urlparse(api.authorize()).query)['state'][0]
        api.callback(state, 'code')
        api.refresh()
        self.assertEqual(self.store.data['auth']['access_token'], 'refreshed')
        self.assertEqual(self.store.data['auth']['refresh_token'], 'rotated')
        with self.assertRaises(ValueError):
            api.callback(state, 'code')

    def test_playlist_loads_every_page_and_handles_both_item_formats(self):
        def transport(method, url, headers, body):
            if '/items?' not in url:
                return {'name': 'My library', 'id': 'x' * 22, 'items': {'total': 51}}
            offset = int(parse_qs(urlparse(url).query)['offset'][0])
            if offset == 0:
                return {'items': [{'item': track(n)} for n in range(50)], 'next': 'more'}
            self.assertEqual(offset, 50)
            return {'items': [{'track': track(50)}], 'next': None}
        result = self.api(transport).playlist('x' * 22)
        self.assertEqual(len(result['tracks']), 51)
        self.assertEqual(result['tracks'][-1]['name'], 'Song 50')

    def test_queue_command_targets_checked_device_and_encodes_uri(self):
        def transport(method, url, headers, body):
            self.assertEqual(method, 'POST')
            self.assertTrue(url.startswith('https://api.spotify.com/v1/me/player/queue?'))
            self.assertEqual(parse_qs(urlparse(url).query), {'uri': [track(1)['uri']], 'device_id': ['phone']})
            return None
        self.api(transport).add(track(1)['uri'], 'phone')

    def test_playlist_url_validation_rejects_non_spotify_hosts(self):
        self.assertEqual(self.m.playlist_id('https://open.spotify.com/playlist/' + 'x' * 22 + '?si=abc'), 'x' * 22)
        self.assertEqual(self.m.playlist_id('spotify:playlist:' + 'x' * 22), 'x' * 22)
        for value in ['https://evil.test/playlist/' + 'x' * 22, '../secrets', 'liked']:
            with self.assertRaises(ValueError):
                self.m.playlist_id(value)

    def test_401_refreshes_once_then_delivers_with_new_token(self):
        def transport(method, url, headers, body):
            if url.endswith('/api/token'):
                return {'access_token': 'refreshed', 'expires_in': 3600}
            if headers['Authorization'] == 'Bearer old-token':
                raise HTTPError(url, 401, 'Expired', {}, None)
            self.assertEqual(headers['Authorization'], 'Bearer refreshed')
            return {'device': {'id': 'phone'}}
        result = self.api(transport).request('GET', '/me/player')
        self.assertEqual(result['device']['id'], 'phone')
        self.assertEqual(self.store.data['auth']['access_token'], 'refreshed')

    def test_429_rejection_is_definite_and_never_retried(self):
        from core import DeliveryError
        calls = []
        def transport(method, url, headers, body):
            calls.append(url)
            raise HTTPError(url, 429, 'Limited', {'Retry-After': '30'}, None)
        with self.assertRaises(DeliveryError) as error:
            self.api(transport).add(track(1)['uri'], 'phone')
        self.assertFalse(error.exception.uncertain)
        self.assertIn('30', str(error.exception))
        self.assertEqual(len(calls), 1)

    def test_write_timeout_and_server_error_are_uncertain_without_retry(self):
        from core import DeliveryError
        for failure in [URLError('Timed out'), HTTPError('https://api.spotify.com', 503, 'Unavailable', {}, None)]:
            calls = []
            def transport(method, url, headers, body):
                calls.append(url)
                raise failure
            with self.assertRaises(DeliveryError) as error:
                self.api(transport).add(track(1)['uri'], 'phone')
            self.assertTrue(error.exception.uncertain)
            self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
