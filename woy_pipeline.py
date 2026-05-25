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


def _clean_date_str(date_str: str) -> str:
    """Strip Eventbrite noise like '+ 9 more', 'at', trailing commas."""
    import re
    s = re.sub(r'\s*\+\s*\d+\s+more.*$', '', date_str, flags=re.IGNORECASE)
    s = re.sub(r'\bat\b', '', s)
    s = s.strip().rstrip(',')
    return s


def parse_event_date(date_str: str) -> datetime | None:
    """Return a timezone-aware datetime (AEST) for the event, or None."""
    if not date_str:
        return None

    cleaned = _clean_date_str(date_str)

    # ISO formats — match exact lengths
    for fmt, length in [
        ("%Y-%m-%dT%H:%M:%S%z", 25),
        ("%Y-%m-%dT%H:%M:%S",   19),
        ("%Y-%m-%d",            10),
    ]:
        try:
            dt = datetime.strptime(cleaned[:length], fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=AEST)
        except ValueError:
            pass

    # Natural-language fallback (dateutil)
    try:
        from dateutil import parser as dp
        today = datetime.now(AEST)
        default_this_year = datetime(today.year, today.month, today.day, tzinfo=AEST)
        dt = dp.parse(cleaned, default=default_this_year, dayfirst=False)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=AEST)
        # If parsed date is in the past, try next year
        if dt.date() < today.date():
            default_next_year = datetime(today.year + 1, 1, 1, tzinfo=AEST)
            dt2 = dp.parse(cleaned, default=default_next_year, dayfirst=False)
            if not dt2.tzinfo:
                dt2 = dt2.replace(tzinfo=AEST)
            if dt2.date() >= today.date():
                return dt2
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
    print(f"  What's On Youth — Weekly Pipeline")
    print(f"  {now.strftime('%A %d %B %Y, %I:%M %p AEST')}")
    print("=" * 60)

    # ── Stage 1: Scrape ────────────────────────────────────────────
    print("\n[1/2] Scraping Eventbrite...")
    events = scrape_events()
    if not events:
        print("  No new events scraped. Pipeline complete.")
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)
        return

    # Sort by parsed date — soonest first; undated events go last
    today = datetime.now(AEST).date()
    def _sort_key(e):
        dt = parse_event_date(e.get("date", ""))
        if dt is None:
            return (1, datetime.max.replace(tzinfo=timezone.utc))
        return (0, dt)
    events.sort(key=_sort_key)

    # Separate past vs future events
    future, past, undated = [], [], []
    for e in events:
        dt = parse_event_date(e.get("date", ""))
        if dt is None:
            undated.append(e)
        elif dt.date() < today:
            past.append(e)
        else:
            future.append(e)

    print(f"  Total scraped  : {len(events)}")
    print(f"  Future events  : {len(future)}")
    print(f"  Past events    : {len(past)} (will be skipped)")
    print(f"  Undated events : {len(undated)} (scheduled 90 min from now)")

    # ── Stage 2: Brand + compute scheduled times ───────────────────
    print("\n[2/2] Branding images...")
    manifest = []
    skip_no_image, skip_brand_error = 0, 0
    all_events = future + undated  # skip past entirely

    for i, e in enumerate(all_events, 1):
        if not e.get("image_url", "").strip():
            print(f"  [{i:02d}] SKIP (no image): {e['title'][:50]}")
            skip_no_image += 1
            continue
        out_path = str(BRANDED_DIR / f"event_{i:02d}.jpg")
        sched = compute_schedule_time(e.get("date", ""))
        try:
            brand_image(e["image_url"], out_path, e["title"])
            manifest.append({
                "num": i,
                "title": e["title"],
                "caption": make_caption(e),
                "url": e["url"],
                "image_path": out_path,
                "scheduled_time": sched,
                "event_date": e.get("date", ""),
            })
        except Exception as exc:
            print(f"  [{i:02d}] ERROR ({exc}): {e['title'][:50]}")
            skip_brand_error += 1

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    schedulable   = sum(1 for e in manifest if e["scheduled_time"])
    unschedulable = sum(1 for e in manifest if not e["scheduled_time"])

    print(f"\n{'='*60}")
    print(f"  PIPELINE REPORT")
    print(f"{'='*60}")
    print(f"  Events scraped    : {len(events)}")
    print(f"  Past events skip  : {len(past)}")
    print(f"  Accepted          : {len(all_events)}")
    print(f"  Branded           : {len(manifest)}")
    print(f"  Skipped (no img)  : {skip_no_image}")
    print(f"  Skipped (error)   : {skip_brand_error}")
    print(f"  Schedulable       : {schedulable}")
    print(f"  Unschedulable     : {unschedulable}")
    print(f"  Manifest          : {MANIFEST_PATH}")
    print(f"  posted_events.txt : updated")
    print(f"{'='*60}")

    if unschedulable:
        print(f"\n  ⚠  {unschedulable} event(s) have unparseable dates:")
        for e in manifest:
            if not e["scheduled_time"]:
                print(f"       - {e['title'][:55]}  (date: {e['event_date']!r})")

    print("\n[Done] Ready for Blotato publish step: python woy_publish_api.py")


if __name__ == "__main__":
    run()
