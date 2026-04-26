const STORAGE_KEY = "cwUrlFixerEnabled";

const IMAGE_EXT = /\.(jpe?g|png|gif|webp|svg|ico|bmp|avif)$/i;

const BLOCKED_PREFIXES = [
  /^\/login(?:\/|$)/i,
  /^\/signup(?:\/|$)/i,
  /^\/logout(?:\/|$)/i,
  /^\/settings(?:\/|$)/i,
  /^\/account(?:\/|$)/i,
  /^\/terms(?:\/|$)/i,
  /^\/privacy(?:\/|$)/i,
  /^\/contact(?:\/|$)/i
];

function isCamwhoresHost(hostname) {
  const h = String(hostname || "").toLowerCase();
  if (!h) return false;
  if (/^([\w-]+\.)*camwhores\.[a-z0-9.-]+$/.test(h)) return true;
  if (/^([\w-]+\.)*camwhoreshd\.[a-z0-9.-]+$/.test(h)) return true;
  return false;
}

function isBlockedPath(pathname) {
  const p = pathname || "/";
  if (IMAGE_EXT.test(p)) return true;
  if (p.toLowerCase().startsWith("/api")) return true;
  if (/\/(admin|dashboard)(?:\/|$)/i.test(p)) return true;
  for (const re of BLOCKED_PREFIXES) {
    if (re.test(p)) return true;
  }
  return false;
}

function matchesRedirectPattern(pathname) {
  const p = pathname || "/";
  if (/^\/videos\/\d+/i.test(p)) return true;
  if (/^\/members\/\d+/i.test(p)) return true;
  if (/^\/albums\/\d+/i.test(p)) return true;
  if (/^\/photos(?:\/|$)/i.test(p)) return true;
  if (/^\/categories(?:\/|$)/i.test(p)) return true;
  if (/^\/search(?:\/|$)/i.test(p)) return true;
  return false;
}

function shouldHandleUrl(href) {
  let u;
  try {
    u = new URL(href);
  } catch {
    return false;
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") return false;
  if (!isCamwhoresHost(u.hostname)) return false;
  if (isBlockedPath(u.pathname)) return false;
  if (!matchesRedirectPattern(u.pathname)) return false;
  return true;
}

function buildCanonical(href) {
  let u;
  try {
    u = new URL(href);
  } catch {
    return null;
  }

  const isSearch = /^\/search(?:\/|$)/i.test(u.pathname);
  let path = u.pathname || "/";
  if (!path.endsWith("/")) path += "/";

  let search = "";
  if (isSearch) {
    search = u.search || "";
  }

  return `https://www.camwhores.tv${path}${search}`;
}

function sameHref(a, b) {
  try {
    return new URL(a).href === new URL(b).href;
  } catch {
    return false;
  }
}

async function isEnabled() {
  const { [STORAGE_KEY]: enabled } = await chrome.storage.sync.get({
    [STORAGE_KEY]: true
  });
  return enabled !== false;
}

chrome.webNavigation.onBeforeNavigate.addListener(
  (details) => {
    if (details.frameId !== 0) return;

    void (async () => {
      if (!(await isEnabled())) return;
      if (!shouldHandleUrl(details.url)) return;

      const next = buildCanonical(details.url);
      if (!next) return;
      if (sameHref(details.url, next)) return;

      try {
        await chrome.tabs.update(details.tabId, { url: next });
      } catch {
        // Tab may have closed; ignore.
      }
    })();
  },
  {
    url: [
      { hostContains: "camwhores" },
      { hostContains: "camwhoreshd" }
    ]
  }
);
