"""Embedded sign-in ("Auth Elements").

An application can show this service's own login/signup pages inside an
iframe on its own page, styled to match its design. The password is still
typed into a page served from this origin, so the embedding page's scripts
can never read it.

How it stays safe:

- Only origins an admin listed on the client (`Client.embed_origins`) may
  embed it. Self-registered clients have none, so they can't embed at all.
- Embed pages are served with `frame-ancestors <that origin>`, so a browser
  refuses to show them inside any other site -- every other page keeps
  refusing all framing.
- The result is a one-time authorization code posted to that exact origin
  with `postMessage` (OAuth "web_message" response mode), never a token.
  The application still exchanges it at /token with its PKCE verifier.
- Styling is a fixed set of design values (colors, font, corner radius),
  each checked against a strict pattern -- never arbitrary CSS, which could
  hide or fake parts of the form.
"""

import json
import re
from urllib.parse import urlsplit

_COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|(rgb|rgba|hsl|hsla)\([0-9.,%\s/]{1,40}\)|[a-zA-Z]{3,20})$")
_LENGTH = re.compile(r"^\d{1,3}(\.\d{1,2})?(px|rem|em)$")
# Unquoted family names only (`Inter, Helvetica Neue, sans-serif` is valid
# CSS): quotes would be HTML-escaped inside the page's <style> block.
_FONT = re.compile(r"^[A-Za-z0-9 ,\-]{1,120}$")
_FRAME_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}

# appearance option -> (CSS custom properties it sets, pattern its value must match)
APPEARANCE_OPTIONS: dict[str, tuple[tuple[str, ...], re.Pattern]] = {
    "colorPrimary": (("--color-primary",), _COLOR),
    "colorPrimaryText": (("--color-primary-contrast",), _COLOR),
    "colorBackground": (("--embed-background",), _COLOR),
    "colorInputBackground": (("--color-surface",), _COLOR),
    "colorText": (("--color-text",), _COLOR),
    "colorTextSecondary": (("--color-text-secondary", "--color-text-tertiary"), _COLOR),
    "colorBorder": (("--color-border", "--color-border-strong"), _COLOR),
    "colorDanger": (("--color-danger",), _COLOR),
    "fontFamily": (("--font-sans",), _FONT),
    "borderRadius": (("--radius-md", "--radius-sm"), _LENGTH),
}
THEMES = {"light", "dark"}


def normalize_origin(value: str) -> str:
    """`scheme://host[:port]`, lower-cased, or ValueError.

    https only, except plain http on localhost for development.
    """
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"not a web origin: {value!r}")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError(f"an origin has no path, query or fragment: {value!r}")
    netloc = parts.netloc.lower()
    host = netloc.rsplit(":", 1)[0] if not netloc.startswith("[") else netloc.split("]")[0] + "]"
    if parts.scheme == "http" and host not in _LOCAL_HOSTS:
        raise ValueError(f"embedding origins must use https (http only for localhost): {value!r}")
    # Browsers leave the default port out of an origin (window.location.origin).
    if (parts.scheme, parts.port) in (("https", 443), ("http", 80)):
        netloc = host
    return f"{parts.scheme}://{netloc}"


def parse_appearance(raw: str | None) -> dict:
    """The valid part of the `appearance` the SDK sent (JSON); the rest is
    dropped silently, so one bad value doesn't break the whole form."""
    if not raw or len(raw) > 2000:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    appearance = {}
    for name, (_, pattern) in APPEARANCE_OPTIONS.items():
        value = data.get(name)
        if isinstance(value, str) and pattern.fullmatch(value.strip()):
            appearance[name] = value.strip()
    if data.get("theme") in THEMES:
        appearance["theme"] = data["theme"]
    return appearance


def css_variables(appearance: dict) -> list[tuple[str, str]]:
    """(custom property, value) pairs for the embed page's style block."""
    pairs = []
    for name, (properties, _) in APPEARANCE_OPTIONS.items():
        if name in appearance:
            pairs.extend((prop, appearance[name]) for prop in properties)
    return pairs


def valid_frame_id(value: str | None) -> bool:
    return bool(value) and bool(_FRAME_ID.fullmatch(value))


def frame_ancestors(origin: str) -> str:
    """The Content-Security-Policy that lets exactly `origin` frame a page."""
    return f"frame-ancestors {origin}"


def encode(origin: str, frame_id: str, appearance: dict) -> str:
    """How an embedded flow is remembered alongside the rest of the flow."""
    return json.dumps({"origin": origin, "frame_id": frame_id, "appearance": appearance})


def decode(value: str | None) -> dict | None:
    """The template context for an embedded flow, or None for a normal one."""
    if not value:
        return None
    data = json.loads(value)
    appearance = data.get("appearance") or {}
    return {
        "origin": data["origin"],
        "frame_id": data["frame_id"],
        "theme": appearance.get("theme"),
        "primary": appearance.get("colorPrimary"),
        "css": css_variables(appearance),
    }
