"""robots.txt parser with wildcard support (* and $).

Python's urllib.robotparser ignores wildcards, but UniBE's robots.txt relies on them
(e.g. `Disallow: /*search_ger.html$`), so we match rules ourselves.
Precedence follows Google's spec: the longest matching rule wins, Allow wins ties.
"""
import re
from urllib.parse import urlsplit


def _to_regex(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    body = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


class Robots:
    def __init__(self, text: str, agent: str):
        agent = agent.lower()
        groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (s.strip() for s in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if rules:  # a user-agent line after rules starts a new group
                    groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(value.lower())
            elif key in ("allow", "disallow") and agents:
                if value:  # empty Disallow means "allow everything"
                    rules.append((key == "allow", value))
        if agents:
            groups.append((agents, rules))

        own = [r for a, r in groups if any(x != "*" and x in agent for x in a)]
        chosen = own or [r for a, r in groups if "*" in a]
        self.rules = [(len(p), allow, _to_regex(p)) for r in chosen for allow, p in r]

    def can_fetch(self, url: str) -> bool:
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        best = None
        for length, allow, rx in self.rules:
            if rx.match(path) and (best is None or length > best[0] or (length == best[0] and allow)):
                best = (length, allow)
        return True if best is None else best[1]
