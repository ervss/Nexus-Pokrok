import re
import httpx


def print_ctx(text: str, token: str, radius: int = 300):
    idx = text.find(token)
    if idx == -1:
        print(f"\nTOKEN '{token}' not found")
        return
    s = max(0, idx - radius)
    e = min(len(text), idx + len(token) + radius)
    print(f"\n=== CONTEXT: {token} ===")
    print(text[s:e])


def main():
    url = "https://bunkr.ac/js/player.enc.js"
    r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://bunkr.ac/"}, timeout=20, verify=False)
    text = r.text
    print("status", r.status_code, "len", len(text))
    for token in ["/api/vs", "SECRET_KEY_", "encode", "decode", "fetch(", "JSON.stringify", "jsSlug", "data-file-id"]:
        print_ctx(text, token)

    print("\n=== STRING LITERALS (top 120) ===")
    strs = re.findall(r"'([^'\\]*(?:\\.[^'\\]*)*)'", text)
    for s in strs[:120]:
        print(s)


if __name__ == "__main__":
    main()
