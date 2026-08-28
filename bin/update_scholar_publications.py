#!/usr/bin/env python3
"""Refresh the site bibliography and citation data from a public Scholar profile."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SOCIALS_FILE = ROOT / "_data" / "socials.yml"
BIBLIOGRAPHY_FILE = ROOT / "_bibliography" / "papers.bib"
CITATIONS_FILE = ROOT / "_data" / "citations.yml"
BASE_URL = "https://scholar.google.com"
USER_AGENT = "Mozilla/5.0 (compatible; leonardozini.github.io scholar updater)"
TITLE_OVERRIDES = {
    "airmlp: a multilayer perceptron neural network for temporal correction of pm2. 5 values in turin": (
        "AirMLP: A Multilayer Perceptron Neural Network for Temporal Correction of PM2.5 Values in Turin"
    )
}
SELECTED_VENUES = {"ECCV", "ICPR", "NeurIPS"}
PAPER_NOTES = {
    "gramsr: visual feature conditioning for diffusion-based super-resolution": "Oral presentation"
}


@dataclass
class ScholarRecord:
    title: str
    year: str
    citations: int
    citation_id: str
    detail_url: str


class ProfileParser(HTMLParser):
    """Extract publication rows from the public Google Scholar profile table."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[ScholarRecord] = []
        self._row: dict[str, str] | None = None
        self._capture: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = attributes.get("class", "") or ""

        if tag == "tr" and "gsc_a_tr" in classes:
            self._row = {}
            return

        if self._row is None:
            return

        if tag == "a" and "gsc_a_at" in classes:
            self._capture = "title"
            self._text = []
            self._row["detail_url"] = attributes.get("href", "") or ""
        elif tag == "a" and "gsc_a_ac" in classes:
            self._capture = "citations"
            self._text = []
        elif tag == "td" and "gsc_a_y" in classes:
            self._capture = "year"
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._row is None:
            return

        if tag in {"a", "td"} and self._capture:
            self._row[self._capture] = "".join(self._text).strip()
            self._capture = None
            self._text = []

        if tag == "tr":
            detail_url = self._row.get("detail_url", "")
            citation_for_view = parse_qs(urlparse(detail_url).query).get("citation_for_view", [""])[0]
            citation_id = citation_for_view.rsplit(":", 1)[-1]
            title = self._row.get("title", "")
            if title and citation_id:
                citations = self._row.get("citations", "0").replace("*", "")
                self.records.append(
                    ScholarRecord(
                        title=title,
                        year=self._row.get("year", ""),
                        citations=int(citations) if citations.isdigit() else 0,
                        citation_id=citation_id,
                        detail_url=urljoin(BASE_URL, detail_url),
                    )
                )
            self._row = None


class DetailParser(HTMLParser):
    """Read Scholar's label/value metadata blocks from one publication page."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}
        self._kind: str | None = None
        self._depth = 0
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return

        classes = (dict(attrs).get("class", "") or "").split()
        if self._kind is not None:
            self._depth += 1
            return

        if "gsc_oci_field" in classes:
            self._kind = "field"
            self._depth = 1
            self._text = []
        elif "gsc_oci_value" in classes:
            self._kind = "value"
            self._depth = 1
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._kind:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "div" or self._kind is None:
            return

        self._depth -= 1
        if self._depth != 0:
            return

        text = re.sub(r"\s+", " ", "".join(self._text)).strip()
        if self._kind == "field":
            self._current_field = text
        elif getattr(self, "_current_field", ""):
            self.fields[self._current_field] = text

        self._kind = None
        self._text = []


def fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def scholar_user_id() -> str:
    content = SOCIALS_FILE.read_text(encoding="utf-8")
    match = re.search(r"^scholar_userid:\s*['\"]?([^\s'\"]+)", content, flags=re.MULTILINE)
    if not match:
        raise ValueError("scholar_userid is missing from _data/socials.yml")
    return match.group(1)


def normalise(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def bibtex_escape(value: str) -> str:
    return (
        normalise(value)
        .replace("\\", r"\\")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("_", r"\_")
    )


def authors_for_bibtex(value: str) -> str:
    names = [normalise(name) for name in value.split(",") if normalise(name)]
    return " and ".join(names) if names else "Leonardo Zini"


def first_author_surname(authors: str) -> str:
    first_author = authors.split(" and ", 1)[0].strip()
    words = re.findall(r"[A-Za-z0-9]+", first_author)
    return words[-1].lower() if words else "zini"


def bib_key(title: str, authors: str, year: str, used: set[str]) -> str:
    words = [word.lower() for word in re.findall(r"[A-Za-z0-9]+", title)]
    significant = next((word for word in words if word not in {"a", "an", "the", "and", "for", "of", "to", "in"}), "paper")
    base = f"{first_author_surname(authors)}{year or 'undated'}{significant}"
    candidate = base
    counter = 2
    while candidate in used:
        candidate = f"{base}{counter}"
        counter += 1
    used.add(candidate)
    return candidate


def venue_fields(metadata: dict[str, str]) -> tuple[str, list[tuple[str, str]]]:
    conference = metadata.get("Conference", "")
    journal = metadata.get("Journal", "")
    book = metadata.get("Book", "")
    publisher = metadata.get("Publisher", "")
    venue = conference or journal or book or publisher

    if conference:
        fields: list[tuple[str, str]] = [("booktitle", conference)]
        entry_type = "inproceedings"
    elif journal:
        fields = [("journal", journal)]
        entry_type = "article"
    elif book:
        fields = [("booktitle", book)]
        entry_type = "incollection"
    else:
        fields = [("howpublished", venue)] if venue else []
        entry_type = "misc"

    for label, key in (("Volume", "volume"), ("Issue", "number"), ("Pages", "pages"), ("DOI", "doi")):
        if metadata.get(label):
            value = metadata[label]
            if key == "pages":
                value = re.sub(r"(?<=\d)-(?=\d)", "--", value)
            fields.append((key, value))

    return entry_type, fields


def venue_abbreviation(metadata: dict[str, str], title: str) -> str:
    corpus = " ".join([title, *metadata.values()]).lower()
    if "arxiv" in corpus:
        return "arXiv"
    if "neurips" in corpus or "neural information processing systems" in corpus:
        return "NeurIPS"
    if "european conference on computer vision" in corpus or "eccv" in corpus:
        return "ECCV"
    if "international conference on pattern recognition" in corpus or "icpr" in corpus:
        return "ICPR"
    if "image analysis and processing" in corpus or "iciap" in corpus:
        return "ICIAP"
    if "sensors" in corpus:
        return "Sensors"
    if "multimedia tools and applications" in corpus:
        return "MTA"
    return ""


def render_bibtex(records: list[ScholarRecord]) -> str:
    entries: list[str] = ["---", "---", ""]
    used_keys: set[str] = set()

    for record in records:
        parser = DetailParser()
        parser.feed(fetch(record.detail_url))
        metadata = {key: normalise(value) for key, value in parser.fields.items()}
        authors = authors_for_bibtex(metadata.get("Authors", ""))
        year_match = re.search(r"\b(19|20)\d{2}\b", metadata.get("Publication date", ""))
        year = year_match.group(0) if year_match else record.year
        entry_type, fields = venue_fields(metadata)
        title = TITLE_OVERRIDES.get(record.title.lower(), record.title)
        key = bib_key(title, authors, year, used_keys)

        lines = [f"@{entry_type}{{{key},", f"  title             = {{{bibtex_escape(title)}}},", f"  author            = {{{bibtex_escape(authors)}}},"]
        for field_name, value in fields:
            lines.append(f"  {field_name:<17} = {{{bibtex_escape(value)}}},")
        lines.append(f"  year              = {{{year}}},")
        abbreviation = venue_abbreviation(metadata, record.title)
        if abbreviation:
            lines.append(f"  abbr              = {{{abbreviation}}},")
        if note := PAPER_NOTES.get(title.lower()):
            lines.append(f"  note              = {{{bibtex_escape(note)}}},")
        lines.append(f"  google_scholar_id = {{{record.citation_id}}},")
        lines.append(f"  website           = {{{record.detail_url}}},")
        if abbreviation in SELECTED_VENUES:
            lines.append("  selected          = {true},")
        lines.append("}")
        entries.extend(lines)
        entries.append("")

    return "\n".join(entries)


def render_citations(records: list[ScholarRecord]) -> str:
    lines = ["metadata:", f"  last_updated: {json.dumps(date.today().isoformat())}", "papers:"]
    for record in records:
        lines.extend(
            [
                f"  {record.citation_id}:",
                f"    citations: {record.citations}",
                f"    title: {json.dumps(normalise(record.title))}",
                f"    year: {json.dumps(record.year)}",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--scholar-id", default=scholar_user_id())
    args = arguments.parse_args()

    profile_url = f"{BASE_URL}/citations?hl=en&user={args.scholar_id}&view_op=list_works&sortby=pubdate"
    parser = ProfileParser()
    parser.feed(fetch(profile_url))
    if not parser.records:
        raise RuntimeError("Google Scholar returned no publication records. It may be rate limiting this request.")

    BIBLIOGRAPHY_FILE.write_text(render_bibtex(parser.records), encoding="utf-8")
    CITATIONS_FILE.write_text(render_citations(parser.records), encoding="utf-8")
    print(f"Updated {len(parser.records)} publications from Google Scholar.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Scholar update failed: {error}", file=sys.stderr)
        raise SystemExit(1)
