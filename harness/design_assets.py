"""Source-only asset consistency checks; never a browser/visual PASS."""
from html.parser import HTMLParser
from pathlib import PurePosixPath
import re
from urllib.parse import unquote, urlsplit


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.resources = []
        self.stylesheets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and "stylesheet" in attrs.get("rel", "").split():
            self.resources.append(attrs.get("href", ""))
            self.stylesheets.append(attrs.get("href", ""))
        if tag in {"script", "img", "iframe", "source", "video", "audio"} and attrs.get("src"):
            self.resources.append(attrs["src"])


def validate(files):
    content = {f["path"]: f["content"] for f in files}
    required = {"prototype/index.html", "prototype/tokens.css", "prototype/components.html", "prototype/system.md"}
    if not required.issubset(content):
        raise ValueError("missing actual design system/prototype files")
    defined = set(re.findall(r"(--[\w-]+)\s*:", content["prototype/tokens.css"]))
    if not defined:
        raise ValueError("tokens.css must contain real CSS variables")
    used = set()
    dependencies = {}
    for path, text in content.items():
        if not path.endswith((".html", ".css", ".js")):
            continue
        refs = []
        if path.endswith(".html"):
            parser = References()
            parser.feed(text)
            refs.extend(parser.resources)
            if not parser.stylesheets:
                raise ValueError(f"HTML must use shared stylesheet: {path}")
        if path.endswith((".html", ".css")):
            refs.extend(re.findall(r"url\(\s*['\"]?([^)'\"\s]+)", text))
            refs.extend(re.findall(r"@import\s+['\"]([^'\"]+)['\"]", text))
            used.update(re.findall(r"var\(\s*(--[\w-]+)", text))
            defined.update(re.findall(r"(--[\w-]+)\s*:", text))
        dependencies[path] = []
        for ref in refs:
            uri = urlsplit(ref)
            if uri.scheme or uri.netloc or ref.startswith("/"):
                raise ValueError(f"external/absolute required resource: {path}: {ref}")
            parts = []
            for part in (PurePosixPath(path).parent / unquote(uri.path)).parts:
                if part == "..":
                    if not parts:
                        raise ValueError("asset escapes submitted bundle")
                    parts.pop()
                elif part != ".":
                    parts.append(part)
            destination = "/".join(parts)
            if destination not in content:
                raise ValueError(f"required asset not preserved in submission: {destination}")
            dependencies[path].append(destination)
    if used - defined:
        raise ValueError(f"undefined CSS variables: {sorted(used - defined)}")
    if not used:
        raise ValueError("design must consume real CSS tokens")
    for path in ("prototype/components.html", "prototype/index.html"):
        seen = set()
        pending = [path]
        while pending:
            p = pending.pop()
            if p not in seen:
                seen.add(p)
                pending.extend(dependencies.get(p, []))
        if "prototype/tokens.css" not in seen:
            raise ValueError(f"component/screen must consume shared tokens.css: {path}")
    return {"scope": "source_only; DOM, interaction and visual review NOT_RUN", "defined_tokens": sorted(defined),
            "used_tokens": sorted(used), "dependencies": dependencies}
