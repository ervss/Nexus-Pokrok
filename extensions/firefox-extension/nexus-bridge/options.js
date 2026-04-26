const DEFAULTS = {
  autoDetectPort: true,
  baseUrl: "http://127.0.0.1:8001",
  pulseEnabled: true,
  notificationsEnabled: false,
  bridgeToken: ""
};

async function loadSettings() {
  const saved = await browser.storage.local.get(Object.keys(DEFAULTS));
  const settings = { ...DEFAULTS, ...saved };
  document.getElementById("baseUrl").value = settings.baseUrl;
  document.getElementById("autoDetectPort").checked = settings.autoDetectPort;
  document.getElementById("pulseEnabled").checked = settings.pulseEnabled;
  document.getElementById("notificationsEnabled").checked = settings.notificationsEnabled;
  document.getElementById("bridgeToken").value = settings.bridgeToken;
}

async function saveSettings() {
  const payload = {
    baseUrl: document.getElementById("baseUrl").value.trim() || DEFAULTS.baseUrl,
    autoDetectPort: document.getElementById("autoDetectPort").checked,
    pulseEnabled: document.getElementById("pulseEnabled").checked,
    notificationsEnabled: document.getElementById("notificationsEnabled").checked,
    bridgeToken: document.getElementById("bridgeToken").value.trim()
  };
  await browser.storage.local.set(payload);
  await browser.runtime.sendMessage({ action: "settingsUpdated" });

  const status = document.getElementById("status");
  status.textContent = "Settings saved.";
  setTimeout(() => {
    status.textContent = "";
  }, 2000);
}

document.getElementById("saveBtn").addEventListener("click", saveSettings);
loadSettings();
