import re
import httpx


def main():
    page_url = "https://bunkr.ac/f/BBLKwPAlBtK2n"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://bunkr.ac/"}

    with httpx.Client(headers=headers, follow_redirects=True, timeout=20, verify=False) as client:
        r = client.get(page_url)
        print("PAGE", r.status_code, len(r.text))
        text = r.text
        patterns = [
            r"/api/[^\s\"'<>]+",
            r"player[^\s\"'<>]+\.js",
            r"fileTracker[^\n]{0,120}",
            r"jsSlug[^\n]{0,120}",
            r"data-file-id=\"[^\"]+\"",
        ]
        for p in patterns:
            m = re.findall(p, text)
            print("\nPATTERN", p, "count", len(m))
            for x in m[:10]:
                print(x)

        enc = client.get("https://bunkr.ac/js/player.enc.js")
        print("\nENC", enc.status_code, len(enc.text))
        enc_text = enc.text
        print(enc_text[:1200])
        for p in [
            r"https?://[^\s\"']+",
            r"/api/[^\s\"']+",
            r"fetch\([^\)]{0,200}\)",
            r"fileId",
            r"decrypt",
            r"encrypt",
        ]:
            m = re.findall(p, enc_text)
            print("\nENC PATTERN", p, "count", len(m))
            for x in m[:10]:
                print(x)


if __name__ == "__main__":
    main()
