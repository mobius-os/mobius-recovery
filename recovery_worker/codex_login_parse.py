"""Pure parsers for the Codex device-auth banner."""

import re


_CODE_RE = re.compile(r"[A-Z0-9]{4,}-[A-Z0-9]{4,}")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_URL_RE = re.compile(r"https://[^\s<>\"']+")


def banner_has_code(output: str) -> bool:
  return "code" in output.lower() and bool(_CODE_RE.search(output))


def parse_login_banner(output: str) -> dict | None:
  clean = _ANSI_RE.sub("", output)
  url_match = _URL_RE.search(clean)
  code_match = _CODE_RE.search(clean)
  if not url_match or not code_match:
    return None
  return {
    "url": url_match.group(0).rstrip(".,;:!?"),
    "code": code_match.group(0),
  }
