// Multi-port detection for different environments
const PORTS = [8000, 8001, 8002, 8003];
let activePort = null;

function setStatus(msg, type = "normal") {
    const el = document.getElementById("status");
    el.textContent = msg;
    el.className = "status " + type;
}

// Helper to check if server is alive on a port
async function checkNexus(port) {
    try {
        // Use a timeout to avoid waiting too long for dead ports
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 1000);

        const res = await fetch(`http://localhost:${port}/api/stats/quality`, {
            method: "GET",
            signal: controller.signal
        });
        clearTimeout(timeoutId);
        return res.ok;
    } catch (e) {
        return false;
    }
}

async function findActivePort() {
    if (activePort && await checkNexus(activePort)) return activePort;

    for (const port of PORTS) {
        if (await checkNexus(port)) {
            activePort = port;
            return port;
        }
    }
    return null;
}

// Helper to get cookies for current tab
async function getCookies(url) {
    return new Promise((resolve) => {
        chrome.cookies.getAll({ url: url }, (cookies) => {
            const cookieString = cookies.map(c => `${c.name}=${c.value}`).join("; ");
            resolve(cookieString);
        });
    });
}

async function apiCall(endpoint, body) {
    setStatus("Connecting...");
    const port = await findActivePort();
    if (!port) {
        setStatus("Error: Is Nexus running? (Checked 8000-8003)", "error");
        throw new Error("Nexus not found");
    }

    const res = await fetch(`http://localhost:${port}/api/bridge${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
    });
    return res.json();
}

document.getElementById("btn-sync").addEventListener("click", async () => {
    setStatus("Syncing...");
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab || !tab.url) return setStatus("No active tab.", "error");

        const cookies = await getCookies(tab.url);
        const data = await apiCall("/sync", {
            url: tab.url,
            cookies: cookies,
            user_agent: navigator.userAgent
        });

        if (data.status === "synced") {
            setStatus(`Synced for ${data.domain}!`, "success");
        } else {
            setStatus("Sync failed.", "error");
        }
    } catch (e) {
        console.error(e);
    }
});

document.getElementById("btn-import").addEventListener("click", async () => {
    setStatus("Importing...");
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab || !tab.url) return setStatus("No active tab.", "error");

        const cookies = await getCookies(tab.url);
        const data = await apiCall("/import", {
            urls: [tab.url],
            batch_name: "Extension Import",
            cookies: cookies
        });

        if (data.status === "ok") {
            setStatus("Import started!", "success");
        } else {
            setStatus("Import failed.", "error");
        }
    } catch (e) {
        console.error(e);
    }
});
