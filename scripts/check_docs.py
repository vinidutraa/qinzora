"""Inspect a built documentation site without network access."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.meta = {}
        self.language = self.canonical = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "html":
            self.language = attributes.get("lang")
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        if tag == "meta":
            name = attributes.get("name", attributes.get("property"))
            self.meta[name] = attributes.get("content")
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonical = attributes.get("href")


def main():
    site = Path("site").resolve()
    count = 0
    for path in site.rglob("*.html"):
        if path.name == "404.html":
            continue
        page = Page()
        page.feed(path.read_text(encoding="utf-8"))
        if not all((page.meta.get("description"), page.meta.get("og:title"), page.canonical)):
            raise ValueError(f"Missing discovery metadata: {path}")
        language = "pt-BR" if "pt-BR" in path.parts else "en"
        if page.language != language:
            raise ValueError(f"Incorrect document language: {path}")
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc or not url.path:
                continue
            target = (path.parent / unquote(url.path)).resolve()
            if url.path.startswith("/"):
                target = site / unquote(url.path).removeprefix("/qinzora/").lstrip("/")
            if not target.exists():
                raise ValueError(f"Broken local link in {path}: {link}")
        count += 1
    if not count or not all((site / name).exists() for name in ("robots.txt", "sitemap.xml")):
        raise ValueError("Missing site pages or crawl configuration")
    print(f"Verified {count} pages: local links, language, canonical and discovery metadata")


if __name__ == "__main__":
    main()
