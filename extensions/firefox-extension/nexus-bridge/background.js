importScripts("lib/compat.js", "lib/api.js");

const PORTS = [8001, 8000, 8002, 8003];
const DEFAULT_SETTINGS = {
  autoDetectPort: true,
  baseUrl: "http://127.0.0.1:8001",
  pulseEnabled: true,
  notificationsEnabled: false,
  bridgeToken: ""
};

let ws = null;
let reconnectTimer = null;
let state = {
  connected: false,
  activeBaseUrl: "",
  lastEvent: "Idle",
  pendingCount: 0
};

async function getSettings() {
  const stored = await browser.storage.local.get(Object.keys(DEFAULT_SETTINGS));
  return { ...DEFAULT_SETTINGS, ...stored };
}

function setBadge(text, color) {
  browser.action.setBadgeText({ text });
  browser.action.setBadgeBackgroundColor({ color });
}

function publishStatePatch(patch) {
  state = { ...state, ...patch };
}

async function discoverBaseUrl(settings) {
  if (!settings.autoDetectPort) {
    return NexusBridgeApi.normalizeBaseUrl(settings.baseUrl);
  }
  const manual = NexusBridgeApi.normalizeBaseUrl(settings.baseUrl);
  if (manual && await NexusBridgeApi.checkHealth(manual).catch(() => false)) {
    return manual;
  }
  for (const port of PORTS) {
    const base = `http://127.0.0.1:${port}`;
    const healthy = await NexusBridgeApi.checkHealth(base).catch(() => false);
    if (healthy) return base;
  }
  return manual;
}

function clearReconnectTimer() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

async function connectPulse() {
  const settings = await getSettings();
  if (!settings.pulseEnabled) {
    publishStatePatch({ connected: false, lastEvent: "Pulse disabled" });
    setBadge("", "#64748b");
    return;
  }

  const baseUrl = await discoverBaseUrl(settings);
  if (!baseUrl) {
    publishStatePatch({ connected: false, lastEvent: "Nexus not found" });
    setBadge("!", "#dc2626");
    scheduleReconnect();
    return;
  }

  const wsUrl = NexusBridgeApi.wsUrlFromBase(baseUrl);
  publishStatePatch({ activeBaseUrl: baseUrl });

  try {
    ws = new WebSocket(wsUrl);
  } catch (error) {
    publishStatePatch({ connected: false, lastEvent: "Pulse connect failed" });
    setBadge("!", "#dc2626");
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    clearReconnectTimer();
    publishStatePatch({ connected: true, lastEvent: "Pulse connected" });
    setBadge("ON", "#16a34a");
  };

  ws.onmessage = async (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (_error) {
      return;
    }

    if (data.type === "new_video") {
      publishStatePatch({ pendingCount: Math.min(state.pendingCount + 1, 99), lastEvent: "New video queued" });
      setBadge(String(state.pendingCount), "#0ea5e9");
      await maybeNotify(settings, "Nexus Pulse", `New video: ${(data.video && data.video.title) || "Unknown"}`);
      return;
    }

    if (data.type === "status_update") {
      const statusLabel = data.status || "updated";
      publishStatePatch({ lastEvent: `Status: ${statusLabel}` });
      if (statusLabel === "ready" || statusLabel === "ready_to_stream") {
        const next = Math.max(0, state.pendingCount - 1);
        publishStatePatch({ pendingCount: next });
        setBadge(next > 0 ? String(next) : "OK", "#16a34a");
      }
      if (statusLabel === "error") {
        setBadge("ERR", "#dc2626");
      }
      return;
    }

    if (data.type === "import_summary") {
      publishStatePatch({ lastEvent: `Batch ${data.batch || "done"}` });
      setBadge("OK", "#16a34a");
      await maybeNotify(settings, "Import finished", `Batch ${data.batch || "completed"} finished.`);
      return;
    }
  };

  ws.onclose = () => {
    publishStatePatch({ connected: false, lastEvent: "Pulse disconnected" });
    setBadge("..", "#f59e0b");
    scheduleReconnect();
  };

  ws.onerror = () => {
    publishStatePatch({ connected: false, lastEvent: "Pulse error" });
    setBadge("!", "#dc2626");
    ws.close();
  };
}

function scheduleReconnect() {
  clearReconnectTimer();
  reconnectTimer = setTimeout(() => {
    connectPulse();
  }, 3000);
}

async function maybeNotify(settings, title, message) {
  if (!settings.notificationsEnabled) return;
  try {
    await browser.notifications.create({
      type: "basic",
      title,
      message
    });
  } catch (_error) {
    // notifications can fail silently if unsupported by host OS
  }
}

async function getActiveTab() {
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  if (!tabs.length || !tabs[0].url) {
    throw new Error("No active tab URL available.");
  }
  return tabs[0];
}

async function getCookieHeader(targetUrl) {
  const cookies = await browser.cookies.getAll({ url: targetUrl });
  return cookies.map((c) => `${c.name}=${c.value}`).join("; ");
}

async function syncActiveTab() {
  const settings = await getSettings();
  const baseUrl = await discoverBaseUrl(settings);
  if (!baseUrl) {
    throw new Error("Nexus server not found. Start dashboard first.");
  }
  const tab = await getActiveTab();
  const cookies = await getCookieHeader(tab.url);
  const data = await NexusBridgeApi.bridgeSync(
    baseUrl,
    {
      url: tab.url,
      cookies,
      user_agent: "Mozilla/5.0 (NexusBridge/1.0; Firefox)"
    },
    settings.bridgeToken
  );
  publishStatePatch({ activeBaseUrl: baseUrl, lastEvent: `Synced ${data.domain || "tab"}` });
  return data;
}

async function importActiveTab() {
  const settings = await getSettings();
  const baseUrl = await discoverBaseUrl(settings);
  if (!baseUrl) {
    throw new Error("Nexus server not found. Start dashboard first.");
  }
  const tab = await getActiveTab();
  const cookies = await getCookieHeader(tab.url);
  const data = await NexusBridgeApi.bridgeImport(
    baseUrl,
    {
      urls: [tab.url],
      batch_name: "Nexus Bridge (Firefox)",
      cookies
    },
    settings.bridgeToken
  );
  publishStatePatch({ activeBaseUrl: baseUrl, lastEvent: "Import started" });
  setBadge("RUN", "#7c3aed");
  return data;
}

browser.runtime.onMessage.addListener((message) => {
  if (!message || !message.action) return undefined;
  if (message.action === "getState") {
    return Promise.resolve({ ...state });
  }
  if (message.action === "syncActiveTab") {
    return syncActiveTab();
  }
  if (message.action === "importActiveTab") {
    return importActiveTab();
  }
  if (message.action === "openDashboard") {
    const target = state.activeBaseUrl || DEFAULT_SETTINGS.baseUrl;
    return browser.tabs.create({ url: `${target}/` });
  }
  if (message.action === "settingsUpdated") {
    if (ws) ws.close();
    connectPulse();
    return Promise.resolve({ ok: true });
  }
  return undefined;
});

browser.runtime.onInstalled.addListener(async () => {
  await browser.storage.local.set({ ...DEFAULT_SETTINGS });
  setBadge("", "#64748b");
  connectPulse();
});

browser.runtime.onStartup.addListener(() => {
  setBadge("", "#64748b");
  connectPulse();
});

