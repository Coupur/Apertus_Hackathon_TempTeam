"""Bounded HTTP reads with exact host boundaries, robots checks, and host pacing."""
import asyncio
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import UnicodeDammit

from .. import config
from ..robots import Robots
from .models import Settings


class FetchError(RuntimeError):
    pass


class BudgetExceeded(FetchError):
    pass


def normalize_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
        if p.scheme.lower() not in ("http", "https") or not p.hostname or p.username or p.password:
            return ""
        if p.port not in (None, 80, 443):
            return ""
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")]
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", urlencode(sorted(query)), ""))
    except ValueError:
        return ""


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


class Boundary:
    def __init__(self, urls: list[str]):
        self.hosts = {host(u) for u in urls if normalize_url(u)}

    def allows(self, url: str) -> bool:
        return bool(normalize_url(url)) and host(url) in self.hosts


@dataclass
class Response:
    url: str
    status: int
    content_type: str
    text: str
    headers: dict


class Fetcher:
    def __init__(self, client: httpx.AsyncClient, boundary: Boundary, settings: Settings):
        self.client, self.boundary, self.settings = client, boundary, settings
        self.content_requests = 0
        self.robots_requests = 0
        self.sem = asyncio.Semaphore(settings.concurrency)
        self.locks: dict[str, asyncio.Lock] = {}
        self.next_request: dict[str, float] = {}
        self.robot_locks: dict[str, asyncio.Lock] = {}
        self.robot_rules: dict[str, Robots] = {}
        self.domain_delays: dict[str, float] = {}

    async def _request(self, url: str, robots: bool = False) -> Response:
        if not self.boundary.allows(url):
            raise FetchError("outside_source_boundary")
        domain = host(url)
        async with self.locks.setdefault(domain, asyncio.Lock()):
            await asyncio.sleep(max(0, self.next_request.get(domain, 0) - time.monotonic()))
            async with self.sem:
                if robots:
                    self.robots_requests += 1
                else:
                    if not self.settings.complete and self.content_requests >= self.settings.max_fetches:
                        raise BudgetExceeded("fetch_budget")
                    self.content_requests += 1
                self.next_request[domain] = time.monotonic() + self.domain_delays.get(domain, self.settings.delay)
                try:
                    async with self.client.stream("GET", url, follow_redirects=False,
                                                  headers={"User-Agent": config.USER_AGENT,
                                                           "Accept-Language": "en,de;q=0.8"}) as response:
                        # A rejected redirect never needs its body downloaded.
                        if response.is_redirect:
                            return Response(str(response.url), response.status_code, "", "", dict(response.headers))
                        content_type = response.headers.get("content-type", "").split(";")[0].strip()
                        if content_type and not any(kind in content_type for kind in ("html", "json", "text/plain")):
                            return Response(str(response.url), response.status_code, content_type, "", dict(response.headers))
                        size, parts = 0, []
                        async for part in response.aiter_bytes():
                            size += len(part)
                            if size > self.settings.max_bytes:
                                raise FetchError("response_too_large")
                            parts.append(part)
                        # HTTPX defaults to UTF-8 when HTTP omits a charset, even
                        # when an HTML meta tag declares Windows-1252 or Latin-1.
                        declared = [response.charset_encoding] if response.charset_encoding else []
                        payload = b"".join(parts)
                        decoded = UnicodeDammit(payload, known_definite_encodings=declared,
                                                is_html="html" in content_type) if payload else None
                        text = decoded.unicode_markup or "" if decoded else ""
                        return Response(str(response.url), response.status_code,
                                        content_type,
                                        text, dict(response.headers))
                except httpx.HTTPError as error:
                    raise FetchError(f"network_{type(error).__name__}") from error

    async def _robots(self, url: str) -> Robots:
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        async with self.robot_locks.setdefault(origin, asyncio.Lock()):
            if origin in self.robot_rules:
                return self.robot_rules[origin]
            target = origin + "/robots.txt"
            body = "User-agent: *\nDisallow: /"
            try:
                for _ in range(6):
                    response = await self._request(target, robots=True)
                    if response.status in (301, 302, 303, 307, 308):
                        target = normalize_url(urljoin(target, response.headers.get("location", "")))
                        if not self.boundary.allows(target):
                            break
                        continue
                    if response.status in (404, 410):
                        body = ""
                    elif response.status == 200 and "html" not in response.content_type:
                        body = response.text
                    break
            except FetchError:
                pass  # Unavailable rules fail closed for this run, then are retried next run.
            rules = Robots(body, config.USER_AGENT)
            parser = RobotFileParser()
            parser.parse(body.splitlines())
            delay = max(self.settings.delay, parser.crawl_delay(config.USER_AGENT) or 0,
                        self.domain_delays.get(host(url), 0))
            self.domain_delays[host(url)] = delay
            self.next_request[host(url)] = max(self.next_request.get(host(url), 0), time.monotonic() + delay)
            self.robot_rules[origin] = rules
            return rules

    async def get(self, url: str) -> Response:
        target = normalize_url(url)
        seen = set()
        for _ in range(6):
            if not self.boundary.allows(target):
                raise FetchError("outside_source_boundary")
            if target in seen:
                raise FetchError("redirect_loop")
            seen.add(target)
            if not (await self._robots(target)).can_fetch(target):
                raise FetchError("robots_disallowed_or_unavailable")
            response = await self._request(target)
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise FetchError("redirect_without_location")
                target = normalize_url(urljoin(target, location))
                continue
            if response.status != 200:
                raise FetchError(f"http_{response.status}")
            return response
        raise FetchError("redirect_limit")
