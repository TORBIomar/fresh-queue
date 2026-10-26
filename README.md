# Fresh Queue

**Version: v1**. Development checkpoint saved on October 26, 2026.
See [NEXT_STEPS.md](NEXT_STEPS.md) to continue development.

A local desktop companion for Spotify Premium. Load a playlist and add batches
of different songs to the upcoming queue on your active iPhone or desktop.
Your playlist order stays untouched.

## Start

Requires **Python 3.10 or newer**. No extra Python packages are needed.

- **Linux:** run `./start.sh`, or `python3 app.py` from this folder.
- **macOS:** open `Start Fresh Queue.command`, or run `python3 app.py`.
- **Windows:** open `start.bat`, or run `py -3 app.py`.

The app opens **http://127.0.0.1:5173** in your desktop browser. Keep its
terminal window open while you use it. To stop, press Ctrl+C in that window.
If port 5173 is already in use, stop the other app using it first.

## Connect once

Your supplied public Client ID is already in `config.json`.

1. In your [Spotify developer dashboard](https://developer.spotify.com/dashboard),
   open the matching app. Make sure Web API access is enabled and this exact
   Redirect URI is saved: **http://127.0.0.1:5173/callback**.
2. In **Users Management**, add the Premium Spotify account you will use if it
   is not already allowed. Personal development apps support up to five users.
3. In Fresh Queue, click **Connect to Spotify** and sign in through Spotify.
   No client secret is required. Do this on the computer running Fresh Queue:
   the callback points back to that computer.

## Queue different songs

1. Paste a playlist link and click **Load playlist**. The app reads every page,
   including playlists containing thousands of tracks. Spotify currently lets
   personal development apps read playlist contents only when you own or
   collaborate on the playlist. Liked Songs is not supported in this version.
2. Start any song in Spotify on your iPhone or desktop. This makes that player
   active. **Check active device** shows where the next batch will be sent.
3. Choose 5, 10, or 25 songs and click **Queue fresh songs**.
4. Listen in Spotify. Add another batch whenever you like.

If you switch between iPhone and desktop, start playback on the desired device
before adding the next batch. Each click targets the device active at that
moment. You can close Fresh Queue after the batch is added; Spotify keeps
playing those queued songs. Reopen Fresh Queue to add more.

Tracks already playing or visible in Spotify's queue are excluded. By default,
the last 50 recently played entries returned by Spotify are also excluded.
Those exclusions are temporary and do not erase a track's future eligibility.

## What the repeat protection means

- Each eligible, unique Spotify track URI is selected at most once **per playlist
  round**, across restarts on this computer. Selection history is separate for
  each Spotify account and playlist.
- Selection means queued or reserved by this app, including songs you skip. The
  app does not monitor all your listening, detect every recording duplicated
  under a different Spotify URI, or guarantee no repeats from playback started
  elsewhere. Different releases of the same recording can have different URIs.
- A round never resets automatically. **Start a new round…** asks before making
  earlier selections eligible again. This does not clear Spotify's queue.
- Duplicate URIs, local files, episodes, removed tracks, and tracks explicitly
  marked unavailable are excluded. Other playback restrictions can still apply.
- Loading an edited playlist again keeps existing progress and includes added
  tracks. This version caches one loaded playlist at a time; round history for
  other playlists remains saved.
- Existing manually queued songs remain ahead of the new batch. The tool does
  not clear or replace your queue. Remove unwanted entries inside Spotify first.
  After the batch ends, Spotify resumes its normal context, which can repeat
  tracks. This is a batch queue tool, not an unattended queue service.
- If a queue request times out, the app stops the batch and keeps the uncertain
  song reserved rather than risk adding it twice. Check Spotify's queue. A track
  can remain reserved after a crash even if delivery did not finish. Other songs
  remain available; starting a new round releases all earlier selections.
- If Spotify rejects a request, confirmed additions remain saved; the rejected
  song remains eligible. Rate limits and account quotas can delay further use.

## Local data

Login tokens, cached track metadata, and selection history are saved in
`.local/state.json` beside the application. The file is atomically replaced
with owner-only permissions where the operating system supports them. Tokens
are not encrypted at rest. Don't share the `.local` folder. It is excluded from
the downloadable source ZIP.

**Disconnect** removes stored login tokens while keeping selection history.
To revoke access at Spotify too, use your
[Spotify apps page](https://www.spotify.com/account/apps/).
Keep the state file to preserve progress when moving or backing up the app.
Deleting it resets the app's repeat memory and removes its local login.

The server listens only on your computer's loopback address. This first version
has no iPhone installation: the desktop tool controls Spotify playing on iPhone.

## Verify

```sh
python3 -m unittest discover -s tests -v
```

The tests cover selection across 1,000 tracks and restarts, exclusions, failures,
OAuth PKCE, paginated playlist import, and the local HTTP boundary. Live Spotify
playback requires your own sign-in and active Premium device.

Independent companion, unaffiliated with Spotify. Music is streamed by Spotify.

References: [PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow),
[queue API](https://developer.spotify.com/documentation/web-api/reference/add-to-queue),
[development restrictions](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).
