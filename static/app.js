'use strict';
const $ = id => document.getElementById(id);
let state = null;
let working = false;
let added = [];

function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').className = error ? 'error' : '';
  $('notice').hidden = !message;
}

function render() {
  if (!state) return;
  $('connection').textContent = state.connected ? `Connected as ${state.profile.display_name}` : 'Spotify isn’t connected';
  $('connection').classList.toggle('connected', state.connected);
  $('setup-label').textContent = state.connected ? 'Spotify connection settings' : 'Connect your Spotify account';
  $('disconnect').hidden = !state.connected;
  $('connect').textContent = state.connected ? 'Reconnect to Spotify' : 'Connect to Spotify';
  $('playlist-loaded').hidden = !state.playlist;
  for (const el of document.querySelectorAll('button, input, select')) el.disabled = working;
  for (const id of ['load', 'playlist-url', 'check-player']) $(id).disabled = working || !state.connected;
  for (const id of ['queue', 'reset']) $(id).disabled = working || !state.connected || !state.playlist;
  if (state.playlist) {
    const p = state.playlist;
    $('playlist-name').textContent = p.name;
    $('playlist-link').href = `https://open.spotify.com/playlist/${encodeURIComponent(p.id)}`;
    $('playlist-meta').textContent = `${p.total.toLocaleString()} unique, playable tracks`;
    $('round').textContent = `Round ${p.round}`;
    $('progress').max = p.total || 1;
    $('progress').value = p.selected;
    $('progress-caption').textContent = `${p.selected.toLocaleString()} selected this round · ${p.remaining.toLocaleString()} not yet selected`;
    $('queue').disabled = working || !state.connected || p.remaining === 0;
  }
  $('batch-empty').hidden = added.length > 0;
  $('batch-count').textContent = added.length ? `${added.length} songs` : '';
  $('batch-list').replaceChildren();
  added.forEach((track, index) => {
    const li = document.createElement('li');
    const number = document.createElement('span'); number.className = 'number'; number.textContent = index + 1;
    const song = document.createElement('div'); song.className = 'song';
    const link = document.createElement('a'); link.textContent = track.name || 'Track';
    link.href = `https://open.spotify.com/track/${encodeURIComponent(track.uri.split(':').pop())}`;
    link.target = '_blank'; link.rel = 'noopener noreferrer';
    const artist = document.createElement('span'); artist.className = 'artist';
    artist.textContent = (track.artists || []).map(a => a.name).join(', ');
    song.append(link, artist);
    const status = document.createElement('span'); status.className = 'added'; status.textContent = 'Queued';
    li.append(number, song, status); $('batch-list').append(li);
  });
}

async function request(path, body) {
  const options = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Fresh-Queue': state.csrf}, body: JSON.stringify(body)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Something went wrong. Try again.');
  return result;
}

async function run(action, message) {
  if (working) return;
  working = true; render(); notice(message);
  try { await action(); }
  catch (error) { notice(error.message || 'Could not reach the app. Check that its terminal window is still open.', true); }
  finally { working = false; render(); }
}

$('connect-form').addEventListener('submit', event => {
  event.preventDefault();
  run(async () => {
    const result = await request('/api/connect', {client_id: $('client-id').value.trim()});
    window.location.assign(result.url);
  }, 'Opening Spotify sign-in…');
});

$('disconnect').addEventListener('click', () => run(async () => {
  state = await request('/api/disconnect', {}); added = []; $('setup').open = true;
  $('device-name').textContent = 'Start a song on your iPhone or desktop, then add your fresh batch here.';
  notice('Disconnected. Your selection history is saved on this computer.');
}, 'Disconnecting…'));

$('playlist-form').addEventListener('submit', event => {
  event.preventDefault();
  run(async () => {
    state = await request('/api/load', {playlist: $('playlist-url').value.trim()});
    notice(`Loaded ${state.playlist.name}. ${state.playlist.total.toLocaleString()} unique, playable tracks are available in this playlist.`);
  }, 'Loading the complete playlist. Large playlists can take a moment…');
});

$('check-player').addEventListener('click', () => run(async () => {
  const device = await request('/api/player', {});
  $('device-name').textContent = device.name ? `Active device: ${device.name}` : 'No active device. Start a song in Spotify on your iPhone or desktop.';
  notice(device.name ? `Spotify is active on ${device.name}.` : 'Start a song in Spotify, then check again.', !device.name);
}, 'Checking Spotify’s active player…'));

$('queue').addEventListener('click', () => run(async () => {
  const result = await request('/api/queue', {count: Number($('batch-size').value), avoid_recent: $('avoid-recent').checked});
  state = result.state; added.push(...result.added);
  $('device-name').textContent = `Last batch sent to ${result.device}.`;
  let message = result.added.length ? `Added ${result.added.length} songs to Spotify’s queue on ${result.device}.` : 'No eligible tracks right now. The remaining songs may be playing, already queued, or in your recent plays.';
  if (state.playlist.remaining === 0) message += ' Every track has been selected. Start a new round when you’re ready.';
  if (result.error) message += ' ' + result.error;
  if (result.uncertain) message += ` Delivery of “${result.uncertain.name}” is unconfirmed. It stays reserved to prevent adding it twice. Check Spotify’s queue.`;
  notice(message, Boolean(result.error));
}, 'Adding fresh songs to Spotify’s queue. Keep this window open…'));

$('reset').addEventListener('click', () => $('reset-dialog').showModal());
$('cancel-reset').addEventListener('click', () => $('reset-dialog').close());
$('confirm-reset').addEventListener('click', () => {
  $('reset-dialog').close();
  run(async () => { state = await request('/api/reset', {}); notice('Started a new round. Previously selected songs are eligible again.'); }, 'Starting a new round…');
});

request('/api/state').then(result => {
  state = result; $('client-id').value = state.client_id;
  $('setup').open = !state.connected;
  if (state.playlist) $('playlist-url').value = `https://open.spotify.com/playlist/${state.playlist.id}`;
  render();
}).catch(error => notice('Could not load Fresh Queue. Check that the app is running, then refresh. ' + error.message, true));
