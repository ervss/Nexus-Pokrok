# Nexus Bridge + Pulse (Firefox)

Firefox WebExtension that connects active browser tabs to the local Nexus/Quantum dashboard bridge API and listens to live Pulse events via WebSocket.

**Chrome / Edge (same feature set):** see `chrome-extension/nexus-bridge` and load it via “Load unpacked” in `chrome://extensions`.

## Features

- `Sync Current Tab` sends URL + cookies to `/api/v1/bridge/sync`
- `Import Current Tab` sends URL + cookies to `/api/v1/bridge/import`
- Live Pulse from `/ws/status` updates extension badge and popup state
- Optional desktop notifications for new video/import summary events
- Optional `X-Nexus-Token` header support

## Load in Firefox (temporary)

1. Open `about:debugging#/runtime/this-firefox`
2. Click `Load Temporary Add-on`
3. Select `firefox-extension/nexus-bridge/manifest.json`

## Recommended server setup

- Run Nexus locally (default `http://127.0.0.1:8001`)
- Keep `/health`, `/api/v1/bridge/sync`, `/api/v1/bridge/import`, and `/ws/status` available
- If bridge token is enabled on backend, set same value in extension settings

## Quick manual test

1. Start Nexus server.
2. Open extension popup and check `Pulse: connected`.
3. Open any supported source page in active tab.
4. Click `Sync Current Tab`, then `Import Current Tab`.
5. Watch dashboard + extension badge react to import progress.
