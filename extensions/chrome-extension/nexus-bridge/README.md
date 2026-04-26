# Nexus Bridge + Pulse (Chrome / Edge)

Chromium WebExtension (Manifest V3) with the same behavior as the Firefox build: send the active tab to the local Nexus/Quantum bridge API and follow live Pulse over WebSocket.

## Load unpacked (development)

1. Open `chrome://extensions` (or `edge://extensions` in Microsoft Edge).
2. Turn on **Developer mode** (left / bottom, depending on version).
3. Click **Load unpacked**.
4. Select the folder `chrome-extension/nexus-bridge` (this directory).

## Features

- **Sync Current Tab** — URL + cookies to `POST /api/v1/bridge/sync`
- **Import Current Tab** — URL + cookies to `POST /api/v1/bridge/import` (batch name: `Nexus Bridge (Chrome)`)
- **Pulse** — `WebSocket` to `/ws/status` (badge + popup)
- Optional desktop notifications (uses `icon.png` for Chrome’s `notifications` API)
- Optional `X-Nexus-Token` in settings

## Recommended server setup

- Run Nexus locally (default `http://127.0.0.1:8001`).
- Expose `/health`, `/api/v1/bridge/sync`, `/api/v1/bridge/import`, and `/ws/status`.
- If the backend sets `NEXUS_BRIDGE_TOKEN`, enter the same value in extension settings.

## Quick manual test

1. Start the Nexus server.
2. Open the extension popup; confirm **Pulse: connected** when the server is up.
3. Open a supported source page in the active tab.
4. Use **Sync Current Tab**, then **Import Current Tab**.
5. Watch the dashboard and the extension badge for progress.

## Firefox

The same extension logic lives under `firefox-extension/nexus-bridge` (Gecko `browser` API + temporary add-on load).
