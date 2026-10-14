"""Normalize DC's image-file routes, never its HTML viewer or article URLs."""

import json
import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

DC_IMAGE_HOST = re.compile(r"dcimg[0-9]+\.dcinside\.(?:co\.kr|com)\Z")
IMAGE_PATHS = {"/viewimage.php", "/dccon.php"}


def miniflux_rewrite_rules():
    """Miniflux uses strconv.Unquote BEFORE compiling the regex.

    JSON quoting is compatible for these ASCII strings; in particular it must
    double regex backslashes. Invalid Go escapes otherwise become empty patterns
    in Miniflux 2.3.3, so never hand-interpolate unquoted regex arguments.
    """
    rules = []
    for suffix in ("co[.]kr", "com"):
        for route in ("viewimage", "dccon"):
            pattern = (
                r'(<img\b[^>]*\ssrc=")https?://dcimg[0-9]+[.]dcinside[.]'
                + suffix
                + "/"
                + route
                + "[.]php[?]"
            )
            replacement = "${1}https://image.dcinside.com/" + route + ".php?"
            rules.append(f"replace({json.dumps(pattern)}|{json.dumps(replacement)})")
    return ",".join(rules)


def normalize_dc_image_url(url):
    try:
        parts = urlsplit(url)
        if (
            parts.scheme not in ("http", "https")
            or not DC_IMAGE_HOST.fullmatch(parts.hostname or "")
            or parts.username is not None
            or parts.password is not None
            or parts.port is not None
            or parts.path not in IMAGE_PATHS
            or not parts.query
        ):
            return url
        # Keep path, raw query encoding/order, and fragment intact.
        return urlunsplit(parts._replace(scheme="https", netloc="image.dcinside.com"))
    except ValueError:
        return url


def normalize_dc_images(content):
    """Also handle cached bodies at render time, without recrawling old posts."""
    soup = BeautifulSoup(content, "html.parser")
    changed = False
    for image in soup.find_all("img", src=True):
        original = image["src"]
        replacement = normalize_dc_image_url(original)
        if replacement != original:
            image["src"] = replacement
            changed = True
    return str(soup) if changed else content
