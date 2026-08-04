"""
Scrape youth events from Eventbrite Melbourne.
Uses Scrapling StealthyFetcher to handle JS-rendered content.
Paginates to collect up to 50 unique events.
Also produces blotato_draft_posts.csv ready for Blotato publishing.
"""

import csv
import re
import sys
import time
from pathlib import Path

# Force UTF-8 output so Unicode characters in event titles don't crash on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from scrapling.fetchers import StealthyFetcher
except ImportError:
    raise SystemExit(
        "Scrapling is not installed. Run: pip install scrapling\n"
        "Then install browser: scrapling install"
    )

BASE_URLS = [
    "https://www.eventbrite.com.au/d/australia--victoria/youth/",
    "https://www.eventbrite.com.au/d/australia--melbourne/teens/",
]
EVENTS_CSV      = "melbourne_youth_events.csv"
BLOTATO_CSV     = "blotato_draft_posts.csv"
POSTED_LOG      = "posted_events.txt"   # persistent record of already-posted event URLs
MAX_EVENTS = 20   # per source URL
MAX_PAGES = 2
PAGE_DELAY = 3  # polite delay between page requests (seconds)


# ---------------------------------------------------------------------------
# Selector helpers — StealthyFetcher returns parsel Selector objects.
# ---------------------------------------------------------------------------

def _text(node) -> str:
    if node is None:
        return ""
    if hasattr(node, "text") and isinstance(getattr(node, "text"), str):
        return node.text.strip()
    parts = node.css("::text").getall()
    return " ".join(p.strip() for p in parts if p.strip())


def _attr(node, name: str, fallback: str = "") -> str:
    if node is None:
        return fallback
    return getattr(node, "attrib", {}).get(name, fallback)


def _css_first(element, selector):
    if hasattr(element, "css_first"):
        return element.css_first(selector)
    results = element.css(selector)
    return results[0] if results else None


# ---------------------------------------------------------------------------
# Text classification helpers
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(
    r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun|Today|Tomorrow|Yesterday|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
    r"\d{1,2}:\d{2}|\d{1,2}\s+\w+,|am|pm)\b",
    re.IGNORECASE,
)

# Junk strings that sometimes appear where the location should be
_JUNK_RE = re.compile(
    r"^(almost full|sold out|selling fast|sales? ends? soon|free|from \$[\d,.]+|"
    r"starts? at \$|[0-9,]+ (follower|attendee)s?|just added|new event)$",
    re.IGNORECASE,
)


def _is_junk(text: str) -> bool:
    return bool(_JUNK_RE.match(text.strip()))


def _classify_paragraphs(card):
    """Return (date_text, location_text) from the <p> nodes inside a card."""
    paras = [_text(p) for p in card.css("p") if _text(p)]
    date_text = ""
    location_text = ""
    for t in paras:
        if not date_text and _DATE_RE.search(t):
            date_text = t
        elif not location_text and not _is_junk(t) and not _DATE_RE.search(t):
            location_text = t
        if date_text and location_text:
            break
    return date_text, location_text


# ---------------------------------------------------------------------------
# Event detail scraper — visits each event page for richer data
# ---------------------------------------------------------------------------

_AGE_RE = re.compile(
    r"""
    (?:
        (?:age[sd]?|for|open\s+to)\s+(?:young\s+people\s+)?(?:age[sd]?\s+)?
        (\d+\s*[-–]\s*\d+)                          # "aged 15-25", "for 18-25"
    |
        (\d+\s*[-–]\s*\d+)\s*(?:year|yr|y\.?o\.?)  # "15-25 year olds"
    |
        (\d+\+)\s*(?:years?)?                        # "18+" or "18+ years"
    |
        under\s+(\d+)                                # "under 25"
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _extract_time(page) -> str:
    """Return event start time as a readable string, e.g. '10:00 AM'."""
    # Try dedicated time/datetime elements
    for sel in [
        "[data-automation='event-details-time']",
        "[data-automation='listing-event-start-time']",
        ".event-details__data time",
        "time[datetime]",
    ]:
        node = _css_first(page, sel)
        if not node:
            continue
        dt_attr = _attr(node, "datetime")
        if dt_attr:
            try:
                from dateutil import parser as dp
                dt = dp.parse(dt_attr)
                h = dt.hour % 12 or 12
                return f"{h}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
            except Exception:
                pass
        raw = _text(node)
        m = re.search(r"\d{1,2}(?::\d{2})?\s*[AaPp][Mm]", raw)
        if m:
            return m.group().strip()

    # Fallback: scan date/time-labelled containers
    for sel in ["[class*='date']", "[class*='time']", ".event-details"]:
        for node in page.css(sel):
            raw = _text(node)
            m = re.search(r"\d{1,2}:\d{2}\s*[AaPp][Mm]", raw)
            if m:
                return m.group().strip()
    return ""


def _extract_eligibility(page, description: str) -> str:
    """Scan description + event body for age range / eligibility."""
    # Build a text corpus: description first, then full event body
    corpus = description
    for sel in [
        "[data-automation='listing-event-description']",
        ".structured-content-rich-text",
        ".event-description",
    ]:
        node = _css_first(page, sel)
        if node:
            extra = " ".join(_text(p) for p in node.css("p"))
            corpus = corpus + " " + extra[:1200]
            break

    m = _AGE_RE.search(corpus)
    if not m:
        return ""
    # Return a small window of context around the match
    start = max(0, m.start() - 8)
    end   = min(len(corpus), m.end() + 12)
    return corpus[start:end].strip().strip(".,")


def fetch_event_details(fetcher, url: str) -> dict:
    """Visit event page; return description, organizer, cost, time, eligibility."""
    out = {"description": "", "organizer": "", "cost": "", "time": "", "eligibility": ""}
    if not url:
        return out
    try:
        time.sleep(2)
        page = fetcher.fetch(url, headless=True, network_idle=True, timeout=30000)
        if not page:
            return out

        # Description — first 1–2 sentences of the event body
        for sel in [
            "[data-automation='listing-event-description'] p",
            ".event-description__content p",
            ".structured-content-rich-text p",
            ".event-description p",
        ]:
            paras = [_text(p) for p in page.css(sel) if len(_text(p)) > 40]
            if paras:
                sentences = re.split(r"(?<=[.!?])\s+", paras[0])
                out["description"] = " ".join(sentences[:2]).strip()
                break

        # Organizer
        for sel in [
            "[data-automation='organizer-profile-name']",
            ".organizer-listing__name a",
            ".organizer-listing__name",
            "[class*='organizer'] [class*='name']",
            "[class*='organizer'] h3",
        ]:
            node = _css_first(page, sel)
            if node:
                name = _text(node)
                if name and 2 < len(name) < 80:
                    out["organizer"] = name
                    break

        # Cost — look for price/free in ticket section
        for sel in [
            "[data-automation='listing-ticket-price']",
            "[class*='ticket-price']",
            ".conversion-bar__panel-info",
        ]:
            node = _css_first(page, sel)
            if node:
                t = _text(node)
                if t:
                    out["cost"] = "Free" if "free" in t.lower() else t[:40]
                    break

        # Fallback: scan all ticket nodes for "free"
        if not out["cost"]:
            nodes = page.css("[class*='ticket']") or page.css("[data-automation*='ticket']")
            combined = " ".join(_text(n) for n in nodes)
            if "free" in combined.lower():
                out["cost"] = "Free"

        # Time
        out["time"] = _extract_time(page)

        # Eligibility / age range
        out["eligibility"] = _extract_eligibility(page, out["description"])

    except Exception as exc:
        print(f"    WARNING (details): {exc}")

    return out


# ---------------------------------------------------------------------------
# Caption generator
# ---------------------------------------------------------------------------

_JOB_KW     = {"job", "career", "employment", "recruit", "hiring", "internship", "traineeship"}
_GRANT_KW   = {"grant", "fund", "scholarship", "bursary", "award", "funding"}
_PROGRAM_KW = {"program", "programme", "workshop", "training", "course", "bootcamp",
               "incubator", "accelerator", "blueprint", "changemaker", "leadership",
               "stem", "girls in business", "gamification"}
_SUPPORT_KW = {"wellbeing", "mental health", "support", "counsell", "therapy",
               "autism", "autistic", "community"}
_LOC_TAGS   = {
    "geelong":   "#Geelong",
    "ballarat":  "#Ballarat",
    "bendigo":   "#Bendigo",
    "melbourne": "#Melbourne",
    "online":    "#Online",
    "virtual":   "#Online",
}


def detect_category(title: str) -> str:
    t = title.lower()
    if any(k in t for k in _JOB_KW):     return "job"
    if any(k in t for k in _GRANT_KW):   return "grant"
    if any(k in t for k in _PROGRAM_KW): return "program"
    if any(k in t for k in _SUPPORT_KW): return "support"
    return "event"


def make_caption(event: dict) -> str:
    title       = event.get("title", "")
    date        = event.get("date", "")
    location    = event.get("location", "")
    url         = event.get("url", "")
    description = event.get("description", "")
    organizer   = event.get("organizer", "")
    cost        = event.get("cost", "")

    category = detect_category(title)
    cat_tag  = {"job": "#YouthJobs", "grant": "#YouthGrants",
                "program": "#YouthPrograms", "support": "#YouthSupport",
                "event": "#YouthEvents"}[category]
    rel_word = {"job": "Offered by", "grant": "Offered by",
                "program": "Delivered by", "support": "Run by",
                "event": "Hosted by"}[category]
    loc_lower = location.lower()
    loc_tag   = next((tag for kw, tag in _LOC_TAGS.items() if kw in loc_lower), "#Victoria")

    lines = [title]

    if description:
        lines += ["", description]

    time_str    = event.get("time", "")
    eligibility = event.get("eligibility", "")

    details = []
    if location:    details.append(f"📍 {location}")
    if date:        details.append(f"📅 {date}")
    if time_str:    details.append(f"⏰ {time_str}")
    if eligibility: details.append(f"👥 For: {eligibility}")
    if cost:        details.append(f"💰 {cost}")
    if details:
        lines += ["", "Key details:"] + details

    if organizer:
        lines += ["", f"{rel_word} {organizer}"]

    lines += ["", f"Apply/Register: {url}"]

    hashtags = ["#WhatsOnYouth", "#VictoriaYouth", cat_tag, loc_tag]
    if cost.lower() == "free":
        hashtags.append("#FreeYouthEvents")
    lines += ["", " ".join(hashtags)]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

CARD_SELECTORS = [
    "[data-testid='event-card']",
    ".eds-event-card-content",
    "article.search-event-card-wrapper",
    ".event-card",
    "[class*='event-card']",
]

# Eventbrite's bot detection is inconsistent (sometimes 200 with real cards,
# sometimes 405 with an empty shell) regardless of source IP. Retry a blocked
# page a few times with backoff before giving up on it.
BLOCK_RETRY_DELAYS = [15, 45, 90]  # seconds


def _fetch_cards(fetcher, url: str) -> list:
    try:
        page = fetcher.fetch(url, headless=True, network_idle=True, timeout=30000)
    except Exception as exc:
        print(f"  WARNING: failed to fetch {url} - {exc}")
        return []

    if not page:
        return []

    for selector in CARD_SELECTORS:
        cards = page.css(selector)
        if cards:
            return cards

    return page.css("article") or page.css("li[class*='event']")


def scrape_page(fetcher, url: str) -> list:
    """Fetch one page and return raw card elements, retrying on a blocked response."""
    time.sleep(PAGE_DELAY)
    cards = _fetch_cards(fetcher, url)
    if cards:
        return cards

    for attempt, delay in enumerate(BLOCK_RETRY_DELAYS, 1):
        print(f"  No cards found - possible block, retrying in {delay}s (attempt {attempt}/{len(BLOCK_RETRY_DELAYS)})...")
        time.sleep(delay)
        cards = _fetch_cards(fetcher, url)
        if cards:
            return cards

    return []


def extract_events(fetcher, base_url: str, seen_urls: set[str]) -> list[dict]:
    """Paginate through one Eventbrite listing URL and collect up to MAX_EVENTS unique events."""
    events: list[dict] = []

    for page_num in range(1, MAX_PAGES + 1):
        if len(events) >= MAX_EVENTS:
            break

        url = base_url if page_num == 1 else f"{base_url}?page={page_num}"
        print(f"  Fetching page {page_num}: {url}")
        cards = scrape_page(fetcher, url)

        if not cards:
            print(f"  No cards found on page {page_num}, stopping pagination.")
            break

        page_added = 0
        for card in cards:
            if len(events) >= MAX_EVENTS:
                break

            # Title
            title = ""
            for sel in ["h2", "h3", "[class*='title']", "[class*='event-name']"]:
                t = _text(_css_first(card, sel))
                if t:
                    title = t
                    break
            if not title:
                continue

            # URL
            link = _css_first(card, "a[href*='/e/']") or _css_first(card, "a")
            href = _attr(link, "href")
            event_url = href if href.startswith("http") else (
                f"https://www.eventbrite.com.au{href}" if href else ""
            )
            if event_url in seen_urls:
                continue
            if event_url:
                seen_urls.add(event_url)

            # Date + Location
            date_text, location_text = _classify_paragraphs(card)
            time_node = _css_first(card, "time[datetime]")
            if time_node:
                date_text = _attr(time_node, "datetime") or date_text

            # Image
            image_url = ""
            for sel in ["img[src]", "img[data-src]"]:
                img = _css_first(card, sel)
                if img:
                    src = _attr(img, "src") or _attr(img, "data-src")
                    if src:
                        image_url = src
                        break

            events.append({
                "title": title,
                "date": date_text,
                "location": location_text,
                "url": event_url,
                "image_url": image_url,
                "description": "",
                "organizer": "",
                "cost": "",
                "time": "",
                "eligibility": "",
            })
            page_added += 1

        # Fetch detail pages after collecting all cards on this listing page
        for ev in events[len(events) - page_added:]:
            if ev["url"]:
                print(f"    Fetching details: {ev['title'][:50]}")
                details = fetch_event_details(fetcher, ev["url"])
                ev.update(details)

        print(f"  -> {page_added} new events collected (total: {len(events)})")

        if page_added == 0:
            break  # no new events on this page, stop early

    return events


# ---------------------------------------------------------------------------
# Duplicate-prevention log
# ---------------------------------------------------------------------------

def load_posted_urls() -> set[str]:
    """Return the set of event URLs already written to Blotato in previous runs."""
    log = Path(POSTED_LOG)
    if not log.exists():
        return set()
    return {line.strip() for line in log.read_text(encoding="utf-8").splitlines() if line.strip()}


def append_posted_urls(events: list[dict]) -> None:
    """Append newly posted event URLs to the persistent log."""
    urls = [e["url"] for e in events if e.get("url")]
    if not urls:
        return
    with open(POSTED_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(urls) + "\n")
    print(f"Posted log   : {Path(POSTED_LOG).resolve()}  (+{len(urls)} URLs logged)")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_events_csv(events: list[dict]) -> None:
    with open(EVENTS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["title", "date", "location", "url", "image_url",
                        "description", "organizer", "cost", "time", "eligibility"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(events)


def save_blotato_csv(events: list[dict]) -> None:
    with open(BLOTATO_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "caption", "url", "image_url", "status"])
        writer.writeheader()
        for e in events:
            writer.writerow({
                "title": e["title"],
                "caption": make_caption(e),
                "url": e["url"],
                "image_url": e["image_url"],
                "status": "DRAFT",
            })


def print_summary(events: list[dict]) -> None:
    print(f"\n{'='*60}")
    print(f"  Victoria Youth + Melbourne Teens Events — {len(events)} scraped")
    print(f"{'='*60}")
    for i, e in enumerate(events, 1):
        print(f"\n[{i:>2}] {e['title']}")
        print(f"      Date     : {e['date'] or 'N/A'}")
        print(f"      Location : {e['location'] or 'N/A'}")
        print(f"      URL      : {e['url'] or 'N/A'}")
    print(f"\n{'='*60}\n")


def print_draft_captions(events: list[dict], n: int = 5) -> None:
    print(f"{'='*60}")
    print(f"  Blotato Draft Captions (first {n})")
    print(f"{'='*60}")
    for i, e in enumerate(events[:n], 1):
        print(f"\n[{i}] {make_caption(e)}")
    print(f"\n{'='*60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    for url in BASE_URLS:
        print(f"Target : {url}")
    print(f"Goal   : up to {MAX_EVENTS} unique events per source across up to {MAX_PAGES} pages\n")

    fetcher = StealthyFetcher()
    posted_urls = load_posted_urls()
    seen_urls: set[str] = set(posted_urls)   # pre-seed with already-posted events
    events: list[dict] = []

    if posted_urls:
        print(f"Skipping     : {len(posted_urls)} previously posted events\n")

    for base_url in BASE_URLS:
        print(f"\n{'─'*60}")
        print(f"  Scraping: {base_url}")
        print(f"{'─'*60}")
        source_events = extract_events(fetcher, base_url, seen_urls)
        events.extend(source_events)

    if not events:
        print(
            "\nWARNING: No events were parsed. Eventbrite may have changed its HTML "
            "structure. Inspect the page and update the card selectors in scrape_page()."
        )
        return

    print_summary(events)
    print_draft_captions(events, n=5)

    save_events_csv(events)
    print(f"Events CSV   : {Path(EVENTS_CSV).resolve()}  ({len(events)} rows)")

    save_blotato_csv(events)
    print(f"Blotato CSV  : {Path(BLOTATO_CSV).resolve()}  ({len(events)} rows, all DRAFT)")

    append_posted_urls(events)


if __name__ == "__main__":
    main()
