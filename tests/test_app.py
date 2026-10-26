import importlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from test_core import track


class AppTests(unittest.TestCase):
    def setUp(self):
        try:
            self.m = importlib.import_module('app')
        except ImportError:
            self.fail('The desktop companion has not been implemented yet')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = self.m.Companion(Path(self.tmp.name) / 'state.json', 'a' * 32)
        self.app.store.data.update({'auth': {'access_token': 'secret-token'}, 'profile': {'id': 'listener', 'display_name': 'Listener'}})

    def test_public_status_never_returns_tokens(self):
        self.assertNotIn('secret-token', json.dumps(self.app.status()))
        self.assertTrue(self.app.status()['connected'])

    def test_queue_excludes_current_queued_recent_and_previous_selections(self):
        class FakeSpotify:
            def request(inner, method, path):
                if path == '/me/player':
                    return {'device': {'id': 'phone', 'name': 'iPhone', 'is_restricted': False}}
                if path == '/me/player/queue':
                    return {'currently_playing': track(1), 'queue': [track(2)]}
                return {'items': [{'track': track(3)}]}
            def add(inner, uri, device):
                self.assertEqual(device, 'phone')
                self.assertEqual(uri, track(4)['uri'])
        self.app.spotify = FakeSpotify()
        self.app.store.data['playlist'] = {'account': 'listener', 'id': 'x' * 22, 'name': 'Library', 'tracks': [track(n) for n in range(1, 5)]}
        result = self.app.queue(10, True)
        self.assertEqual([t['name'] for t in result['added']], ['Song 4'])
        self.assertEqual(self.app.status()['playlist']['selected'], 1)
        self.assertEqual(self.app.queue(10, True)['added'], [])

    def test_no_active_device_keeps_selection_history_untouched(self):
        class FakeSpotify:
            def request(inner, method, path):
                return None
        self.app.spotify = FakeSpotify()
        self.app.store.data['playlist'] = {'account': 'listener', 'id': 'x' * 22, 'name': 'Library', 'tracks': [track(1)]}
        with self.assertRaises(ValueError):
            self.app.queue(10, True)
        self.assertEqual(self.app.status()['playlist']['selected'], 0)

    def test_queue_size_validated_before_any_network_call(self):
        class NoNetwork:
            def request(inner, *args):
                self.fail('Invalid requests should not contact Spotify')
        self.app.spotify = NoNetwork()
        for count in [0, -1, 26, True, '10']:
            with self.assertRaises(ValueError):
                self.app.queue(count, True)

    def test_http_rejects_cross_origin_and_missing_csrf_header(self):
        server = self.m.make_server(self.app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = 'http://127.0.0.1:' + str(server.server_port)
        with urlopen(url + '/api/state') as response:
            state = json.load(response)
        self.assertNotIn('secret-token', json.dumps(state))
        for headers in [{'Content-Type': 'application/json'},
                        {'Content-Type': 'application/json', 'X-Fresh-Queue': state['csrf'], 'Origin': 'https://evil.test'}]:
            req = Request(url + '/api/disconnect', method='POST', data=b'{}', headers=headers)
            with self.assertRaises(HTTPError) as error:
                urlopen(req)
            self.assertEqual(error.exception.code, 403)
        req = Request(url + '/api/disconnect', method='POST', data=b'{}', headers={
            'Content-Type': 'application/json', 'X-Fresh-Queue': state['csrf'], 'Origin': url})
        with urlopen(req) as response:
            self.assertFalse(json.load(response)['connected'])


if __name__ == '__main__':
    unittest.main()
