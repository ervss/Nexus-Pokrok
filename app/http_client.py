import aiohttp

http_session = None

def get_http_session():
    global http_session
    if http_session is None:
        # Create a generic fallback session if one hasn't been instantiated by main.py
        resolver = aiohttp.AsyncResolver(nameservers=["8.8.8.8", "8.8.4.4", "1.1.1.1"])
        connector = aiohttp.TCPConnector(limit=200, limit_per_host=50, keepalive_timeout=60, resolver=resolver)
        timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=600)
        http_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    return http_session
