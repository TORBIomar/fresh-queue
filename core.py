"""Persistent selection history; tracks are marked before queue delivery."""
import json
import os
import random
import re
import tempfile
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}
        if not isinstance(self.data, dict):
            raise ValueError('Invalid state file. Restore a backup before continuing.')

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.fresh-queue-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                json.dump(self.data, out, ensure_ascii=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)


class ShuffleBag:
    def __init__(self, store, account, playlist, tracks):
        self.store = store
        self.key = account + ':' + playlist
        self.tracks = {}
        for item in tracks:
            if (item and item.get('type') == 'track' and not item.get('is_local')
                    and item.get('is_playable') is not False
                    and re.fullmatch(r'spotify:track:[A-Za-z0-9]{22}', item.get('uri', ''))):
                self.tracks.setdefault(item['uri'], item)
        self.record = store.data.setdefault('rounds', {}).setdefault(self.key, {'used': [], 'round': 1})

    @property
    def total(self):
        return len(self.tracks)

    @property
    def used(self):
        return set(self.record['used'])

    def choose(self, count, excluded=()):
        available = [t for uri, t in self.tracks.items() if uri not in self.used and uri not in excluded]
        return random.SystemRandom().sample(available, min(count, len(available)))

    def reserve(self, uri):
        if uri not in self.used:
            self.record['used'].append(uri)
            self.store.save()

    def release(self, uri):
        self.record['used'] = [u for u in self.record['used'] if u != uri]
        self.store.save()

    def reset(self):
        self.record['used'] = []
        self.record['round'] += 1
        self.store.save()

    def stats(self):
        used = len(set(self.tracks) & self.used)
        return {'total': self.total, 'selected': used, 'remaining': self.total - used,
                'round': self.record['round']}


class DeliveryError(Exception):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def enqueue(bag, tracks, send):
    result = {'added': [], 'error': None, 'uncertain': None}
    for item in tracks:
        bag.reserve(item['uri'])
        try:
            send(item['uri'])
        except DeliveryError as exc:
            result['error'] = str(exc)
            if exc.uncertain:
                result['uncertain'] = item
            else:
                bag.release(item['uri'])
            break
        result['added'].append(item)
    return result
