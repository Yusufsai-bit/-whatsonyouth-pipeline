"""
What's On Youth — Automated Weekly Pipeline
Scrape → Brand → Write manifest with scheduled publish times.
Run every Monday. Blotato publish step handled by Claude cron job.
"""
import json, sys
from pathlib import Path
from datetime import datetime, timedelta, timezone, time as dtime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from brand_image import brand_image

BRANDED_DIR = Path(__file__).parent / "branded_posts"
BRANDED_DIR.mkdir(exist_ok=True)
MANIFEST_PATH = BRANDED_DIR / "manifest.json"

AEST = timezone(timedelta(hours=10))
DAYS_BEFORE = 3
FALLBACK_DAYS = 1


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


def make_caption(e: dict) -> str:
    title       = e.get("title", "")
    date        = e.get("date", "")
    location    = e.get("location", "")
    url         = e.get("url", "")
    description = e.get("description", "")
    organizer   = e.get("organizer", "")
    cost        = e.get("cost", "")

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

    time_str    = e.get("time", "")
    eligibility = e.get("eligibility", "")

    details = []
    if location:    details.append(f"\U0001f4cd {location}")
    if date:        details.append(f"\U0001f4c5 {date}")
    if time_str:    details.append(f"⏰ {time_str}")
    if eligibility: details.append(f"\U0001f465 For: {eligibility}")
    if cost:        details.append(f"\U0001f4b0 {cost}")
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


def parse_event_date(date_str: str) -> datetime | None:
    """Return a timezone-aware datetime (AEST) for the event, or None."""
    if not date_str:
        return None

    # ISO formats — try longest first
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str[:len(fmt)], fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=AEST)
        except ValueError:
            pass

    # Natural-language fallback (dateutil)
    try:
        from dateutil import parser as dp
        today = datetime.now(AEST)
        dt = dp.parse(date_str, default=datetime(today.year, 1, 1, tzinfo=AEST))
        if dt.date() < today.date():
            dt = dp.parse(date_str, default=datetime(today.year + 1, 1, 1, tzinfo=AEST))
        return dt
    except Exception:
        return None


def compute_schedule_time(date_str: str) -> str | None:
    """
    Return UTC ISO 8601 scheduledTime:
      - 3 days before event at 9 AM AEST
      - If that's past, 1 day before at 9 AM AEST
      - If that's also past (event today/yesterday), schedule 1 hour from now
      - Returns None only if the event date itself can't be parsed
    """
    dt = parse_event_date(date_str)
    if dt is None:
        return None

    today = datetime.now(AEST).date()
    event_date = dt.date()

    for days_before in (DAYS_BEFORE, FALLBACK_DAYS):
        post_date = event_date - timedelta(days=days_before)
        if post_date > today:
            post_dt = datetime.combine(post_date, dtime(9, 0, 0), tzinfo=AEST)
            return post_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if post_date == today:
            # Schedule 90 minutes from now so it's definitely in the future
            post_dt = datetime.now(AEST) + timedelta(minutes=90)
            return post_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Event already passed both thresholds — post 90 min from now as last resort
    post_dt = datetime.now(AEST) + timedelta(minutes=90)
    return post_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scrape_events() -> list[dict]:
    from scrape_eventbrite_youth import BASE_URLS, extract_events, load_posted_urls, append_posted_urls
    from scrapling.fetchers import StealthyFetcher
    fetcher = StealthyFetcher()
    seen_urls = set(load_posted_urls())
    events: list[dict] = []
    for base_url in BASE_URLS:
        events.extend(extract_events(fetcher, base_url, seen_urls))
    append_posted_urls(events)
    return events


def run():
    now = datetime.now(AEST)
    print("=" * 60)
    print("  What's On Youth — Weekly Pipeline")
    print(f"  {now.strftime('%A %d %B %Y, %I:%M %p AEST')}")
    print("=" * 60)

    # ── Stage 1: Scrape ────────────────────────────────────────────
    print("\n[1/2] Scraping Eventbrite...")
    events = scrape_events()
    if not events:
        print("  No events scraped. Pipeline aborted.")
        sys.exit(1)
    print(f"  {len(events)} events found.")

    # ── Stage 2: Brand + compute scheduled times ───────────────────
    print("\n[2/2] Branding images...")
    manifest = []
    for i, e in enumerate(events, 1):
        if not e.get("image_url", "").strip():
            print(f"  [{i:02d}] SKIP (no image): {e['title'][:50]}")
            continue
        out_path = str(BRANDED_DIR / f"event_{i:02d}.jpg")
        try:
            brand_image(e["image_url"], out_path, e["title"])
            manifest.append({
                "num": i,
                "title": e["title"],
                "caption": make_caption(e),
                "url": e["url"],
                "image_path": out_path,
                "scheduled_time": compute_schedule_time(e.get("date", "")),
            })
        except Exception as exc:
            print(f"  [{i:02d}] ERROR ({exc}): {e['title'][:50]}")

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    schedulable = sum(1 for e in manifest if e["scheduled_time"])
    print(f"\n  Branded:   {len(manifest)}/{len(events)}")
    print(f"  Scheduled: {schedulable}")
    print(f"  Manifest:  {MANIFEST_PATH}")
    print("\n[Done] Ready for Blotato publish step.")


if __name__ == "__main__":
    run()
