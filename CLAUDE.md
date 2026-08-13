# What's On Youth — Social Media Pipeline

## What This Is

Automated social media pipeline for **@whatson.youth** (Instagram + Facebook).
Scrapes youth events from Eventbrite Victoria/Melbourne, applies WOY branding to event images, and schedules posts to Instagram and Facebook via Blotato.

**Platform**: whatsonyouth.com.au  
**Accounts**: Instagram @whatson.youth | Facebook @whatson.youth

---

## Pipeline Flow

```
Eventbrite (2 URLs)
       ↓
scrape_eventbrite_youth.py   →  melbourne_youth_events.csv
                                blotato_draft_posts.csv
                                posted_events.txt (duplicate log)
       ↓
brand_image.py               →  branded JPEGs (1080×1350px)
       ↓
woy_pipeline.py              →  branded_posts/manifest.json
       ↓
woy_publish_api.py           →  Blotato API → IG + FB scheduled posts
```

---

## Scripts

### `scrape_eventbrite_youth.py`
Scrapes two Eventbrite listing URLs, paginates up to 2 pages, fetches detail pages for enriched metadata, generates captions, and outputs CSVs.

- **Sources**:
  - `https://www.eventbrite.com.au/d/australia--victoria/youth/`
  - `https://www.eventbrite.com.au/d/australia--melbourne/teens/`
- **Outputs**: `melbourne_youth_events.csv`, `blotato_draft_posts.csv`
- **Duplicate prevention**: loads `posted_events.txt` at startup and skips already-posted events. Appends new URLs after each run. Delete `posted_events.txt` to reset.
- **Run**: `python scrape_eventbrite_youth.py`

### `brand_image.py`
Takes an event image URL and title, downloads the image, composites it onto a 1080×1350px canvas with blurred background, WOY footer, and icon.

- **Output size**: 1080×1350px JPEG at 95% quality
- **Footer templates** (auto-detected from event title keywords):
  - `dark` — jobs, careers, grants, leadership, STEM, business
  - `teal` — wellbeing, mental health, community, support, autism
  - `light` — everything else (default)
- **Icon**: placed at (28, 28) on blurred background layer, BEFORE sharp flyer is composited (so it never overlaps the event photo)
- **Assets** (all in `assets/` subfolder):
  - `WOY_footer_light_1080x120_centered.png`
  - `WOY_footer_dark_1080x120_centered.png`
  - `WOY_footer_teal_1080x120_centered.png`
  - `WOY_top_left_true_icon_72x72.png`
- **Run**: `python brand_image.py` (generates a single test preview to Downloads/)

### `batch_brand.py`
Batch-processes all events from `melbourne_youth_events.csv` through `brand_image.py`. Outputs branded JPEGs to `branded_posts/`.

- **Run**: `python batch_brand.py`

### `woy_pipeline.py`
Weekly orchestrator. Scrapes events, brands each image, computes scheduled publish times (3 days before event at 9 AM AEST, fallback 1 day before), writes `branded_posts/manifest.json`.

- **Run**: `python woy_pipeline.py`

### `woy_publish_api.py`
Reads `manifest.json`, uploads each branded JPEG to Blotato presigned URL, then schedules an Instagram post and a Facebook post for each event.

- **Blotato account IDs**: Instagram `43819` | Facebook `43819` (page ID: `1035821056287360`)
- **Requires**: `BLOTATO_API_KEY` environment variable
- **Rate limit**: 2-second delay between posts (Blotato ceiling: 30 req/min)
- **Run**: `python woy_publish_api.py`

### `woy_upload.py`
Single-image uploader. PUTs a file to a Blotato presigned URL.

- **Run**: `python woy_upload.py <image_path> <presigned_url>`

### `run_woy_pipeline.ps1`
PowerShell runner for Windows Task Scheduler. Runs the full pipeline (scrape + brand + publish) every Monday at 8:00 AM. Logs to `woy_pipeline_log.txt`.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BLOTATO_API_KEY` | Yes | Blotato REST API key for scheduling posts |

Set in PowerShell: `$env:BLOTATO_API_KEY = "your-key-here"`  
Or add to Windows Environment Variables via System Settings.

---

## Assets

All branding assets live in the `assets/` subfolder (relative to the scripts):

```
assets/
  WOY_footer_light_1080x120_centered.png
  WOY_footer_dark_1080x120_centered.png
  WOY_footer_teal_1080x120_centered.png
  WOY_top_left_true_icon_72x72.png
```

---

## Output Files

| File | Description |
|---|---|
| `melbourne_youth_events.csv` | Raw scraped event data (21 columns) |
| `blotato_draft_posts.csv` | Event captions ready for Blotato import |
| `posted_events.txt` | Persistent log of posted event URLs (delete to reset) |
| `branded_posts/event_NN.jpg` | Branded 1080×1350px event images |
| `branded_posts/manifest.json` | Full post schedule with captions and times |

---

## Setup on a New Machine

```bash
# 1. Clone the repo
git clone https://github.com/Yusufsai-bit/-whatsonyouth-pipeline
cd -whatsonyouth-pipeline

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install Scrapling browser
scrapling install

# 4. Set API key
$env:BLOTATO_API_KEY = "your-key-here"

# 5. Test branding (generates branded_preview.jpg in Downloads/)
python brand_image.py

# 6. Run full scrape
python scrape_eventbrite_youth.py
```

---

## Running End-to-End

```bash
python woy_pipeline.py       # scrape + brand + write manifest
python woy_publish_api.py    # upload + schedule to Blotato
```

Or via the PowerShell runner (also sets up Task Scheduler):
```powershell
.\run_woy_pipeline.ps1
```

---

## Caption Logic

Captions are auto-generated per event category:

| Category | Detected by keywords | Hashtag |
|---|---|---|
| job | job, career, internship, traineeship | #YouthJobs |
| grant | grant, fund, scholarship, bursary | #YouthGrants |
| program | workshop, training, bootcamp, leadership | #YouthPrograms |
| support | wellbeing, mental health, autism | #YouthSupport |
| event | (default) | #YouthEvents |

Location hashtag auto-detected from event location field: Melbourne, Geelong, Ballarat, Bendigo, Online, Victoria (default).

---

## Key Design Decisions

- **Icon placement**: Icon is composited BEFORE the sharp event photo so it never visually overlaps the photo — it sits in the blurred background border area.
- **Duplicate prevention**: `posted_events.txt` is the source of truth. Pre-seeded into `seen_urls` at scrape time so already-posted events are never re-scraped or re-posted.
- **Footer selection**: Keyword-based — matches title text against sets of keywords. First match wins (dark > teal > light).
- **Scheduling**: Posts are timed 3 days before the event at 9 AM AEST. If that window has already passed, falls back to 1 day before, then 90 minutes from now as a last resort.

---

## Claude Code Workflow

- **Context management**: Run `/compact` at ~50% context usage to avoid truncation
- **Complex tasks**: Use `/plan` before starting multi-step work
- **Diagnostics**: Run `/doctor` if Claude Code behaves unexpectedly
- **Long-running commands**: Run as background tasks for better log visibility

## Git Commit Rules

Create **separate commits per file** — do not bundle multiple file changes into one commit. Each file gets its own descriptive commit. This keeps history clean and easy to revert or cherry-pick.
