# Financial Listings Monitoring Tool

Desktop monitoring application built with PySide6 that continuously checks:

- FINRA Daily List: <https://otce.finra.org/otce/dailyList>
- OTC Markets: <https://www.otcmarkets.com/>

## Features

- Multi-ticker monitoring with configurable polling interval
- Dual-source matching logic:
  - FINRA-only alert
  - OTC-only alert
  - combined FINRA + OTC alert
- Mandatory second-confirmation check before alerting
- Duplicate alert suppression
- Date range filtering
- Desktop popups and source-specific sounds
- Alert history and live log window
- Dark mode toggle and font-size adjustment

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Architecture

- `src/scraper/finra_scraper.py` - FINRA Daily List parsing (HTML + downloadable files fallback)
- `src/scraper/otc_scraper.py` - OTC Markets status/grace scraping (DOM + `__NEXT_DATA__`)
- `src/monitor_worker.py` - background monitoring loop, dual-source logic, verification, dedupe
- `src/alert_manager.py` - popup + sound dispatch
- `src/ui/main_window.py` - desktop user interface
