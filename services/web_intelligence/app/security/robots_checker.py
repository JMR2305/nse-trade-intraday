"""Robots.txt policy checker."""
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.logging import get_logger

logger = get_logger(__name__)


class RobotsChecker:
    """Check robots.txt policies for target URLs."""

    def __init__(self) -> None:
        self._cache: dict[str, str | None] = {}
        # None sentinel means "blocked/unknown" — do not retry

    async def is_allowed(
        self,
        url: str,
        user_agent: str | None = None,
        *,
        robots_policy: str | None = None,
    ) -> bool:
        """Check if a URL is allowed by robots.txt.

        If ``robots_policy`` is ``"allow"`` (explicit operator override for a
        reviewed source), the check is skipped entirely and True is returned.

        On any fetch failure or parse failure the method returns **False**
        (fail-closed), not True.  This ensures ambiguous robot status never
        silently permits crawling.

        Returns:
            True if allowed, False if disallowed or ambiguous/failed.
        """
        # Operator-reviewed explicit allow override — skip robots.txt
        if robots_policy == "allow":
            logger.debug("robots_override_allow", url=url)
            return True

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False

        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        user_agent = user_agent or settings.default_user_agent

        try:
            robots_content = await self._fetch_robots(robots_url, user_agent)
            if robots_content is None:
                # None means blocked/unavailable (non-404 4xx or fetch error)
                logger.warning("robots_blocked_unavailable", url=url, robots_url=robots_url)
                return False
            if robots_content == "":
                # Empty string = 404, no robots.txt = allow all
                return True

            return self._check_path(robots_content, parsed.path, user_agent)
        except Exception as e:
            logger.warning("robots_check_failed", url=url, error=str(e))
            return False  # Fail closed on any unexpected error

    async def _fetch_robots(self, robots_url: str, user_agent: str) -> str | None:
        """Fetch robots.txt content.  Cached per domain.

        Returns:
            ""    if robots.txt does not exist (404).
            str   with content if fetched successfully.
            None  if fetch failed or returned a non-404 4xx — caller must
                  treat as blocked.
        """
        if robots_url in self._cache:
            return self._cache[robots_url]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    robots_url,
                    headers={"User-Agent": user_agent},
                )
                if response.status_code == 404:
                    # Explicit "no robots.txt" — allow
                    self._cache[robots_url] = ""
                    return ""
                if response.status_code >= 400:
                    # Non-404 4xx → treat as blocked; cache to avoid hammering
                    logger.warning(
                        "robots_fetch_4xx",
                        url=robots_url,
                        status=response.status_code,
                    )
                    self._cache[robots_url] = None  # type: ignore[assignment]
                    return None
                content = response.text
                self._cache[robots_url] = content
                return content
        except Exception as e:
            logger.warning("robots_fetch_failed", url=robots_url, error=str(e))
            # Do NOT cache network errors — they may be transient; caller will
            # fail closed regardless.
            return None

    def _check_path(self, robots_content: str, path: str, user_agent: str) -> bool:
        """Parse robots.txt and check if path is allowed.

        Simple parser — handles User-agent and Disallow/Allow directives.
        """
        lines = robots_content.splitlines()
        current_agent = None
        applicable_rules: list[tuple[str, str]] = []  # (directive, path)

        agent_name = user_agent.split("/")[0] if "/" in user_agent else user_agent

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if ":" not in line:
                continue

            directive, value = line.split(":", 1)
            directive = directive.strip().lower()
            value = value.strip()

            if directive == "user-agent":
                current_agent = value
            elif directive in ("disallow", "allow") and current_agent:
                # Check if this rule applies to our agent
                if current_agent == "*" or agent_name.lower() in current_agent.lower():
                    applicable_rules.append((directive, value))

        # Process rules in order (most specific last wins)
        allowed = True
        for directive, rule_path in applicable_rules:
            if path.startswith(rule_path) or (rule_path.endswith("/") and path.startswith(rule_path.rstrip("/"))):
                if directive == "disallow" and rule_path:
                    allowed = False
                elif directive == "allow":
                    allowed = True

        return allowed
