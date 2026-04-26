const STORAGE_KEY = "cwUrlFixerEnabled";

const checkbox = document.getElementById("enabled");
const statusEl = document.getElementById("status");

function setStatus(on) {
  statusEl.textContent = on
    ? "On — mirror domains redirect to www.camwhores.tv."
    : "Off — no automatic redirects.";
  statusEl.className = on ? "on" : "off";
}

async function load() {
  const { [STORAGE_KEY]: enabled } = await chrome.storage.sync.get({
    [STORAGE_KEY]: true
  });
  const on = enabled !== false;
  checkbox.checked = on;
  setStatus(on);
}

checkbox.addEventListener("change", async () => {
  const on = checkbox.checked;
  await chrome.storage.sync.set({ [STORAGE_KEY]: on });
  setStatus(on);
});

load();
