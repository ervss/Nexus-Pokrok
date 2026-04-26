const pulseStatusEl = document.getElementById("pulseStatus");
const activeBaseEl = document.getElementById("activeBase");
const lastEventEl = document.getElementById("lastEvent");
const statusLineEl = document.getElementById("statusLine");

function setStatus(message, isError = false) {
  statusLineEl.textContent = message;
  statusLineEl.classList.toggle("error", Boolean(isError));
}

function renderState(state) {
  pulseStatusEl.textContent = state.connected ? "Pulse: connected" : "Pulse: disconnected";
  activeBaseEl.textContent = `Server: ${state.activeBaseUrl || "not connected"}`;
  lastEventEl.textContent = `Last event: ${state.lastEvent || "idle"}`;
}

async function refreshState() {
  try {
    const state = await browser.runtime.sendMessage({ action: "getState" });
    renderState(state || {});
  } catch (_error) {
    setStatus("Cannot talk to background worker.", true);
  }
}

async function callAction(action, successText) {
  setStatus("Working...");
  try {
    await browser.runtime.sendMessage({ action });
    setStatus(successText);
    await refreshState();
  } catch (error) {
    setStatus(error.message || "Operation failed.", true);
  }
}

document.getElementById("btnSync").addEventListener("click", () => {
  callAction("syncActiveTab", "Sync done.");
});

document.getElementById("btnImport").addEventListener("click", () => {
  callAction("importActiveTab", "Import triggered.");
});

document.getElementById("btnDashboard").addEventListener("click", () => {
  browser.runtime.sendMessage({ action: "openDashboard" });
});

document.getElementById("openOptions").addEventListener("click", (event) => {
  event.preventDefault();
  browser.runtime.openOptionsPage();
});

refreshState();
