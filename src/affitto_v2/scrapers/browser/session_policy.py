from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HardwareMimetics:
    user_agent: str
    device_memory: int
    hardware_concurrency: int
    webgl_vendor: str
    webgl_renderer: str
    canvas_noise_mode: str = "static"


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    site: str
    browser_mode: str
    user_agent: str
    hardware: HardwareMimetics
    pacing_gamma_shape: float
    pacing_gamma_scale: float
    bootstrap_urls: tuple[str, ...]
    bootstrap_timeout_ms: int


_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)

_DEFAULT_HARDWARE = HardwareMimetics(
    user_agent=_DEFAULT_USER_AGENT,
    device_memory=16,
    hardware_concurrency=8,
    webgl_vendor="Intel Inc.",
    webgl_renderer="Intel(R) Iris(TM) Graphics Xe",
)

_DEFAULT_BOOTSTRAP_URLS = (
    "https://www.gstatic.com/generate_204",
    "https://www.google.it/generate_204",
    "https://www.cloudflare.com/cdn-cgi/trace",
)

_SITE_POLICIES: dict[str, SessionPolicy] = {
    "idealista": SessionPolicy(
        site="idealista",
        browser_mode="managed_stable",
        user_agent=_DEFAULT_USER_AGENT,
        hardware=_DEFAULT_HARDWARE,
        pacing_gamma_shape=2.0,
        pacing_gamma_scale=1.5,
        bootstrap_urls=_DEFAULT_BOOTSTRAP_URLS,
        bootstrap_timeout_ms=5000,
    ),
    "immobiliare": SessionPolicy(
        site="immobiliare",
        browser_mode="managed_stable",
        user_agent=_DEFAULT_USER_AGENT,
        hardware=_DEFAULT_HARDWARE,
        pacing_gamma_shape=2.0,
        pacing_gamma_scale=1.5,
        bootstrap_urls=_DEFAULT_BOOTSTRAP_URLS,
        bootstrap_timeout_ms=5000,
    ),
}


def get_session_policy(site: str) -> SessionPolicy:
    return _SITE_POLICIES.get(site, _SITE_POLICIES["immobiliare"])


__all__ = [
    "HardwareMimetics",
    "SessionPolicy",
    "get_session_policy",
]
