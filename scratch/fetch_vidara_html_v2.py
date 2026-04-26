import httpx
import asyncio

async def fetch_vidara():
    url = "https://vidara.so/e/XW9Na9PdjUrE"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': 'https://vidara.so/'
    }
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers, verify=False) as client:
        resp = await client.get(url)
        with open('scratch/vidara_source_utf8.html', 'w', encoding='utf-8') as f:
            f.write(resp.text)

if __name__ == "__main__":
    asyncio.run(fetch_vidara())
