import importlib
import tempfile
import unittest
from pathlib import Path


def track(n):
    return {'uri': 'spotify:track:' + str(n).zfill(22), 'name': f'Song {n}',
            'artists': [{'name': 'Artist'}], 'type': 'track', 'is_local': False}


class CoreTests(unittest.TestCase):
    def setUp(self):
        try:
            self.m = importlib.import_module('core')
        except ImportError:
            self.fail('The fresh queue engine has not been implemented yet')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'

    def store(self):
        return self.m.Store(self.path)

    def test_no_repeats_across_restart_and_all_1000_tracks_are_reachable(self):
        items = [track(i) for i in range(1000)]
        engine = self.m.ShuffleBag(self.store(), 'account', 'playlist', items)
        picked = []
        for _ in range(40):
            batch = engine.choose(25)
            for item in batch:
                engine.reserve(item['uri'])
            picked.extend(t['uri'] for t in batch)
            engine = self.m.ShuffleBag(self.store(), 'account', 'playlist', items)
        self.assertEqual(len(picked), 1000)
        self.assertEqual(len(set(picked)), 1000)
        self.assertEqual(engine.choose(25), [])

    def test_filters_duplicates_local_missing_and_excluded_tracks(self):
        items = [track(1), track(1), track(2), None,
                 {**track(3), 'is_local': True}, {**track(4), 'is_playable': False}]
        engine = self.m.ShuffleBag(self.store(), 'a', 'p', items)
        self.assertEqual([x['uri'] for x in engine.choose(25, {track(1)['uri']})], [track(2)['uri']])
        self.assertEqual(engine.total, 2)

    def test_new_tracks_join_existing_round_without_resetting_history(self):
        engine = self.m.ShuffleBag(self.store(), 'a', 'p', [track(1)])
        engine.reserve(track(1)['uri'])
        engine = self.m.ShuffleBag(self.store(), 'a', 'p', [track(1), track(2)])
        self.assertEqual(engine.choose(25), [track(2)])

    def test_accounts_have_independent_history(self):
        engine = self.m.ShuffleBag(self.store(), 'a', 'p', [track(1)])
        engine.reserve(track(1)['uri'])
        other = self.m.ShuffleBag(self.store(), 'b', 'p', [track(1)])
        self.assertEqual(other.choose(1), [track(1)])

    def test_new_round_requires_explicit_reset(self):
        engine = self.m.ShuffleBag(self.store(), 'a', 'p', [track(1)])
        engine.reserve(track(1)['uri'])
        self.assertEqual(engine.choose(1), [])
        engine.reset()
        self.assertEqual(engine.choose(1), [track(1)])

    def test_timeout_preserves_uncertain_reservation_and_stops_batch(self):
        engine = self.m.ShuffleBag(self.store(), 'a', 'p', [track(1), track(2)])
        def send(uri):
            raise self.m.DeliveryError('Timed out', uncertain=True)
        result = self.m.enqueue(engine, engine.choose(2), send)
        self.assertEqual(len(result['added']), 0)
        self.assertIsNotNone(result['uncertain'])
        self.assertEqual(len(engine.choose(2)), 1)

    def test_definite_rejection_does_not_use_up_a_track(self):
        engine = self.m.ShuffleBag(self.store(), 'a', 'p', [track(1)])
        def send(uri):
            raise self.m.DeliveryError('Rate limited', uncertain=False)
        result = self.m.enqueue(engine, engine.choose(1), send)
        self.assertEqual(result['added'], [])
        self.assertEqual(engine.choose(1), [track(1)])

    def test_partial_success_is_preserved(self):
        engine = self.m.ShuffleBag(self.store(), 'a', 'p', [track(1), track(2), track(3)])
        calls = []
        def send(uri):
            calls.append(uri)
            if len(calls) == 2:
                raise self.m.DeliveryError('No device', uncertain=False)
        result = self.m.enqueue(engine, [track(1), track(2), track(3)], send)
        self.assertEqual(result['added'], [track(1)])
        self.assertEqual({t['uri'] for t in engine.choose(25)}, {track(2)['uri'], track(3)['uri']})

    def test_reservation_is_saved_before_network_delivery(self):
        engine = self.m.ShuffleBag(self.store(), 'a', 'p', [track(1)])
        def send(uri):
            reopened = self.m.ShuffleBag(self.store(), 'a', 'p', [track(1)])
            self.assertEqual(reopened.choose(1), [])
        self.assertEqual(self.m.enqueue(engine, [track(1)], send)['added'], [track(1)])

    def test_corrupt_state_is_not_silently_reset(self):
        self.path.write_text('{broken')
        with self.assertRaises(ValueError):
            self.store()


if __name__ == '__main__':
    unittest.main()
