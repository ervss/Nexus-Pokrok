from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db, Video
import aiohttp
import logging
import urllib.parse
import os
import re
import asyncio

router = APIRouter(tags=["proxy"])

@router.get("/api/v1/proxy")
@router.get("/api/proxy")
async def universal_cors_proxy(url: str):
    """
    Universal CORS proxy to bypass external CDN restrictions.
    Usage: /api/proxy?url=https://example.com/image.jpg
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter required")

    # Clean up URL (sometimes passed with double protocol or spaces)
    url = url.strip()
    if url.startswith('https//'): url = url.replace('https//', 'https://', 1)
    if url.startswith('http//'): url = url.replace('http//', 'http://', 1)

    try:
        domain_parts = url.split('/')
        base_domain = domain_parts[0] + '//' + domain_parts[2] if len(domain_parts) > 2 else url

        # Pick correct Referer so CDNs don't 403 the thumbnail request
        if "camwhores" in url or "cwvids" in url or "cwstore" in url:
            _referer = "https://www.camwhores.tv/"
        elif "hqporner" in url or "mydaddy" in url:
            _referer = "https://hqporner.com/"
        elif "pixeldrain" in url:
            _referer = "https://pixeldrain.com/"
        elif "eporner" in url:
            _referer = "https://www.eporner.com/"
        elif "xvideos" in url:
            _referer = "https://www.xvideos.com/"
        elif "leakporner" in url or "58img" in url:
            _referer = "https://leakporner.com/"
        elif "rec-ur-bate" in url or "recurbate" in url:
            _referer = "https://rec-ur-bate.com/"
        else:
            _referer = base_domain
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": _referer,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
        }

        from app.http_client import get_http_session
        # Use the global http_session for better performance
        async with get_http_session().get(url, timeout=15, headers=headers, ssl=False) as resp:
            if resp.status != 200:
                logging.warning(f"Proxy upstream returned {resp.status} for {url}")
                raise HTTPException(status_code=resp.status, detail=f"Upstream returned {resp.status}")

            content = await resp.read()
            content_type = resp.headers.get('Content-Type', 'image/jpeg') # Fallback to jpeg

            return Response(
                content=content,
                media_type=content_type,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "public, max-age=86400", # Cache for 24h
                    "X-Proxy-Source": "Quantum-CORS"
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Detailed CORS proxy error for {url}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")


@router.get("/hls_proxy")
async def hls_proxy(url: str, referer: str = ""):
    """
    HLS rewriting proxy — rewrites m3u8 playlists so .ts segments are fetched
    through this proxy with the correct Referer header (fixes Pornhub/WhoresHub 404s).
    Usage: /hls_proxy?url=https://cdn.../master.m3u8&referer=https://www.pornhub.com/
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Invalid URL")

    # Derive referer from URL origin if not supplied
    if not referer:
        parts = url.split("/")
        referer = parts[0] + "//" + parts[2] + "/" if len(parts) > 2 else url

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": referer,
        "Origin": referer.rstrip("/"),
    }

    is_m3u8 = ".m3u8" in url.lower()

    # Load cookies for VK/OK if available
    cookies = {}
    is_vk = any(d in url.lower() for d in ['vk.com', 'vk.video', 'vkvideo.ru', 'okcdn.ru', 'vkvideo.net', 'vk.ru'])
    if is_vk:
        for cf in ['vk.netscape.txt', 'cookies.netscape.txt']:
            if os.path.exists(cf):
                try:
                    with open(cf, 'r') as f:
                        for line in f:
                            if not line.startswith('#') and line.strip():
                                parts = line.strip().split('\t')
                                if len(parts) >= 7:
                                    cookies[parts[5]] = parts[6]
                    break
                except: pass

    try:
        from app.http_client import get_http_session
        timeout = aiohttp.ClientTimeout(total=30)
        async with get_http_session().get(url, headers=headers, cookies=cookies if cookies else None, timeout=timeout, ssl=False) as resp:
            if resp.status != 200:
                raise HTTPException(resp.status, f"Upstream returned {resp.status}")
            content_type = resp.headers.get("Content-Type", "")
            raw = await resp.read()

        # Decide: m3u8 playlist or raw segment
        if is_m3u8 or "mpegurl" in content_type.lower():
            body = raw.decode("utf-8", errors="replace")
            base_url = url.rsplit("/", 1)[0] + "/"
            encoded_referer = urllib.parse.quote(referer, safe="")
            lines = []
            for line in body.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    # Resolve segment/variant/key URIs robustly (absolute, root-relative,
                    # protocol-relative, ../ traversal, query-only, etc.).
                    seg_url = urllib.parse.urljoin(url, stripped)
                    encoded_seg = urllib.parse.quote(seg_url, safe="")
                    lines.append(f"/hls_proxy?url={encoded_seg}&referer={encoded_referer}")
                else:
                    lines.append(line)
            return Response(
                content="\n".join(lines),
                media_type="application/vnd.apple.mpegurl",
                headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"},
            )

        # Raw segment (.ts / .aac / etc.)
        ct = content_type or "video/MP2T"
        return Response(
            content=raw,
            media_type=ct,
            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"HLS proxy error for {url}: {e}")
        raise HTTPException(500, f"HLS proxy error: {e}")


@router.get("/stream_torrent/{port}/{file_path:path}")
async def stream_torrent_proxy(port: int, file_path: str, request: Request):
    """
    Proxies the internal webtorrent stream to the external client so we don't rely on localhost mapping.
    """
    from app.torrent_manager import torrent_manager
    if port in torrent_manager.available_ports or port not in range(8002, 8100):
        raise HTTPException(status_code=403, detail="Invalid or inactive torrent stream port")

    from app.http_client import get_http_session

    # If the UI requests the "resolve" path, we query the webtorrent root to find the actual video file index
    if file_path == "resolve":
        try:
            async with get_http_session().get(f"http://127.0.0.1:{port}/") as root_resp:
                html = await root_resp.text()
                # webtorrent-cli serves a basic HTML page with hrefs like <a href="/0">...</a>
                # Let's find the first one that looks like a video file. If we can't tell, we just default to /0.
                # A simple regex to find href="/number" ending in mp4/mkv/etc.
                import re
                match = re.search(r'href="(/(\d+))"[^>]*>([^<]+(?:mp4|mkv|avi|webm|mov))<', html, re.IGNORECASE)
                if match:
                    file_path = match.group(2)
                else:
                    file_path = "0"
        except Exception as e:
            logging.warning(f"Could not resolve WebTorrent index, defaulting to 0: {e}")
            file_path = "0"

    target_url = f"http://127.0.0.1:{port}/{file_path}"

    headers = dict(request.headers)
    headers.pop("host", None)

    try:
        upstream_response = await get_http_session().get(target_url, headers=headers, allow_redirects=True)

        excluded_headers = {
            'content-encoding', 'content-length', 'transfer-encoding',
            'connection', 'keep-alive', 'host', 'server', 'vary'
        }
        response_headers = {k: v for k, v in upstream_response.headers.items() if k.lower() not in excluded_headers}

        if 'Content-Length' in upstream_response.headers:
            response_headers['Content-Length'] = upstream_response.headers['Content-Length']
        if 'Content-Range' in upstream_response.headers:
            response_headers['Content-Range'] = upstream_response.headers['Content-Range']

        async def content_streamer():
            try:
                async for chunk in upstream_response.content.iter_chunked(64 * 1024):
                    yield chunk
            finally:
                upstream_response.close()

        return StreamingResponse(
            content_streamer(),
            status_code=upstream_response.status,
            headers=response_headers,
            media_type=upstream_response.headers.get("Content-Type", "video/mp4")
        )
    except Exception as e:
        logging.error(f"Torrent proxy error: {e}")
        raise HTTPException(status_code=502, detail="Torrent stream not available")

@router.get("/download/{video_id}")
async def download_direct(video_id: int, db: Session = Depends(get_db)):
    v = db.query(Video).get(video_id)
    if not v: raise HTTPException(404)
    async def iter_file():
        async with aiohttp.ClientSession() as session:
            async with session.get(v.url) as resp:
                async for chunk in resp.content.iter_chunked(64*1024): yield chunk

    # Create ASCII-safe filename for compatibility
    safe = "".join([c for c in v.title if c.isalnum() or c in (' ','-','_')]).strip()
    if not safe:
        safe = f"video_{video_id}"

    # Use RFC 5987 encoding for Unicode support (filename* parameter)
    import urllib.parse
    encoded_title = urllib.parse.quote(v.title.encode('utf-8'))

    # Provide both ASCII fallback and UTF-8 encoded filename
    content_disposition = f'attachment; filename="{safe}.mp4"; filename*=UTF-8\'\'{encoded_title}.mp4'

    return StreamingResponse(iter_file(), headers={"Content-Disposition": content_disposition})

def get_stream_url(video_id: int):
    return f"/stream_proxy/{video_id}.mp4"
