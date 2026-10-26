# Resume after v1

This is a working local development checkpoint, saved on October 26, 2026.
Live Spotify OAuth and playback have not yet been verified with the user's
account. No new features or background queue service are in progress.

## Current behavior

- Python standard-library app running at http://127.0.0.1:5173 on the desktop.
- OAuth PKCE with no client secret. The supplied public Client ID is in
  `config.json`; the registered redirect is http://127.0.0.1:5173/callback.
- Complete paginated import of a playlist the user owns or collaborates on,
  using Spotify's `/playlists/{id}/items` endpoint.
- Persistent selection history per account and playlist, with batches of
  5, 10, or 25 songs added to the active Spotify device's queue.
- Excludes already selected tracks, the current song, visible queue entries,
  and optionally the last 50 recent plays returned by Spotify.
- A round resets only after explicit confirmation. Uncertain queue delivery
  remains reserved to avoid duplicate additions after a timeout or crash.
- Responsive browser interface. The desktop controls Spotify playback on
  iPhone or desktop; there is no standalone iPhone app in v1.

## Verification at this checkpoint

24 automated tests passed. Desktop (1280 x 1000) and narrow (390 x 844) browser
checks passed with simulated Spotify responses, covering all 1,000 test tracks,
two distinct batches, saved progress after reload, device checks, and round reset
cancellation/confirmation. No app console errors were observed. Browser QA
scripts and simulated account data are development scratch files, not part of
the shipped application.

## Next session

1. Run `python3 app.py` from the repository root.
2. Click **Connect to Spotify** and complete sign-in on the desktop. Confirm
   the Spotify account has Premium and is allowed under the developer app's
   Users Management settings.
3. Load a real playlist, check the imported track count, and check the active
   device after starting playback on iPhone or desktop.
4. Add a small batch and verify the actual Spotify queue, then repeat after
   restarting Fresh Queue to verify saved selection history in live use.
5. Decide which workflow to improve next after trying this batch-based version.

The tool appends to the existing queue. It cannot clear Spotify's queue through
the current official queue API, and it does not run an unattended queue service.
Once the batch finishes, Spotify returns to its normal playback context.

Keep `.local/state.json` private and preserve it if you want to keep selection
history. It is ignored by Git and omitted from source archives. An account's
login can be removed with **Disconnect** without resetting selection history.

Run the suite before changes are committed:

```sh
python3 -m unittest discover -s tests -v
node --check static/app.js
```
