# AI-Powered B2B Outreach Platform

A production-grade Python CLI that automates the full outbound prospecting loop:

```
Ocean.io → Prospeo → EazyReach → Brevo
(lookalikes) (contacts)  (emails)  (send)
```

---

## Folder Structure

```
automated-outreach-pipeline/
├── main.py                            # CLI entry point
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
│
├── src/
│   ├── config.py                      # Pydantic-Settings: all env/API config
│   ├── logger.py                      # Rich + rotating file logger
│   ├── models.py                      # All Pydantic domain models
│   ├── utils.py                       # Helpers: dedup, export, email template
│   │
│   ├── services/
│   │   ├── ocean_service.py           # Ocean.io lookalike API
│   │   ├── prospeo_service.py         # Prospeo domain-search API
│   │   ├── eazyreach_service.py       # EazyReach LinkedIn→email API
│   │   └── brevo_service.py           # Brevo transactional email API
│   │
│   └── pipeline/
│       └── outreach_pipeline.py       # Stage orchestrator with Rich progress
│
├── tests/
│   ├── test_models.py                 # Domain model unit tests
│   ├── test_utils.py                  # Helper unit tests
│   ├── test_services.py               # Service HTTP tests (responses mock)
│   └── test_pipeline.py              # Pipeline integration tests (pytest-mock)
│
├── data/                              # CSV + JSON exports (auto-created)
├── logs/                              # Rotating log files (auto-created)
└── docs/
    └── api_reference.md               # curl examples for every API
```

---

## Setup

### A. Create virtual environment

**Mac / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

> **Note:** This project requires Python 3.12. If your default `python3` is newer (e.g. 3.14), use the explicit binary:
> ```bash
> /opt/homebrew/bin/python3.12 -m venv venv
> ```

### B. Install dependencies

```bash
pip install -r requirements.txt
```

### C. Configure environment

```bash
cp .env.example .env
# Open .env and fill in your API keys
```

| Variable | Where to get it |
|---|---|
| `OCEAN_API_KEY` | https://ocean.io → Settings → API |
| `PROSPEO_API_KEY` | https://prospeo.io → Dashboard → API Key |
| `EAZYREACH_API_KEY` | Contact EazyReach support |
| `BREVO_API_KEY` | https://app.brevo.com → SMTP & API → API Keys |

> **No keys?** Every service has a mock fallback — the pipeline runs end-to-end with synthetic data when keys are absent.

---

## Run

```bash
# Standard run
python main.py stripe.com

# Limit to 5 lookalike companies
python main.py stripe.com --limit 5

# Skip email sending (dry-run)
python main.py stripe.com --dry-run

# Debug logging
python main.py stripe.com --verbose

# Combine options
python main.py stripe.com --limit 3 --dry-run --verbose
```

### Safety Checkpoint

Before any emails are sent, the pipeline prints a summary and requires explicit confirmation:

```
╭──────────────────────────────────╮
│         OUTREACH SUMMARY         │
│  Source domain     stripe.com    │
│  Companies found       10        │
│  Contacts found        47        │
│  Verified emails       23        │
╰──────────────────────────────────╯

Proceed to send emails? (y/n):
```

---

## Run Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=src --cov-report=term-missing

# Specific test file
pytest tests/test_models.py -v

# Specific test class
pytest tests/test_services.py::TestOceanServiceHTTP -v
```

---

## Output

After each run, timestamped files are written to `data/`:

| File | Contents |
|---|---|
| `contacts_YYYYMMDD_HHMMSS.csv` | All discovered + enriched contacts |
| `email_results_YYYYMMDD_HHMMSS.csv` | Email send status per contact |
| `results_YYYYMMDD_HHMMSS.json` | Full pipeline result as JSON |

---

## Email Template

**Subject:** `Quick idea for {company}`

```
Hi {first_name},

I came across {company} and noticed your role as {title}.

I wanted to reach out because we help companies improve outbound
prospecting and automate outreach.

Would love to connect.

Best regards,
Gurukiran
```

---

## Git Commit Plan

```
chore: initialise project structure and venv

feat(config): pydantic-settings config with full .env support

feat(models): Company, Contact, EmailResult, PipelineResult models

feat(logger): rich console + rotating file logger

feat(utils): domain normalisation, dedup, email templating, CSV/JSON export

feat(services/ocean): OceanService with tenacity retry and mock fallback

feat(services/prospeo): ProspeoService with pagination and mock fallback

feat(services/eazyreach): EazyReachService with enrichment and mock fallback

feat(services/brevo): BrevoService with bulk send and mock fallback

feat(pipeline): OutreachPipeline orchestrator with Rich progress display

feat(cli): main.py with argparse, dry-run, verbose, and error handling

test: unit + integration tests for models, utils, services, pipeline

docs: README, .env.example, api_reference.md
```

---

## TODO

- [ ] Confirm EazyReach API base URL and auth scheme with their support team
- [ ] Add async/concurrent HTTP for faster bulk processing (`httpx` + `asyncio`)
- [ ] Add SQLite store to skip already-processed contacts across runs
- [ ] Add Slack webhook notification on pipeline completion
- [ ] Add HTML email support in Brevo service
- [ ] Add `--resume` flag to continue from a previous run's JSON output
