# Cambodia Real Estate Listing Scraper

A small Python command-line scraper for property listings on
[Realestate.com.kh](https://www.realestate.com.kh/). It reads listing data
embedded in the site's pages and can optionally visit each listing's detail
page to collect additional property features.

The project is intended for learning, market research, and experimentation
with property-price prediction. Site page structures and available fields can
change, so check the output and scraper behavior periodically.

## Dataset snapshot

The local `sale1.json` dataset was checked on **October 6, 2026** and contained
**5,010 records with 5,010 unique property IDs**. It combines results collected
from sale-search pages, category searches, and location searches. All records
in this snapshot have latitude and longitude values. See
[`DATASET_SUMMARY.md`](DATASET_SUMMARY.md) for the listing-type, province, and
property-type breakdown. Counts are point-in-time and can change as the
dataset is updated.

## Features

- Scrapes sale, rental, or filtered search-result pages.
- Collects property IDs, listing type, property type, prices, areas, rooms,
  address, coordinates, and other available listing fields.
- Converts displayed prices, areas, room counts, and floor numbers to numeric
  values where possible.
- Optionally fetches detail pages for title type, furnished status, amenities,
  condition, and parking when those are available.
- Writes JSON and saves each search-results page before moving to the next.
- Keeps one record per property ID and listing type. A later scrape keeps an
  existing record unchanged; it only adds property/type combinations not
  already in the output. Existing prices and features are not refreshed.

## Requirements

- Python 3.10 or newer
- No third-party Python packages; the scraper uses the standard library.

## Setup on Windows

Open PowerShell in the project folder and create a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation in the current terminal, allow scripts for
this process and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

There are no packages to install. Confirm Python is available:

```powershell
python --version
```

## Usage

Scrape the first 10 pages of the sale search, including detail pages:

```powershell
python scraper.py --url "https://www.realestate.com.kh/buy/" --start-page 1 --pages 10 --details --output sale.json
```

Scrape rental search results into a separate file:

```powershell
python scraper.py --url "https://www.realestate.com.kh/rent/" --start-page 1 --pages 10 --details --output rent.json
```

Filtered searches are passed through `--url`. Quote the complete URL so
PowerShell handles query-string characters correctly:

```powershell
python scraper.py --url "https://www.realestate.com.kh/buy/?categories=Condo&order_by=floor-area-desc" --start-page 1 --pages 10 --details --output sale.json
```

### Resuming a batch

`--pages 10` means up to 10 consecutive result pages. If pages 1–10 finished,
continue from page 11:

```powershell
python scraper.py --url "https://www.realestate.com.kh/buy/" --start-page 11 --pages 10 --details --output sale.json
```

The scraper saves each completed page immediately. If a run fails while
requesting a page, previously completed pages remain saved; resume by starting
at the page that failed. A missing page or HTTP error can indicate unavailable
pagination or a site/network issue; it does not by itself establish why the
request failed.

### Options

| Option | Description | Default |
| --- | --- | --- |
| `--url` | Search URL, including any filters | `https://www.realestate.com.kh/buy/` |
| `--start-page` | First result page number | `1` |
| `--pages` | Maximum consecutive pages to request | `1` |
| `--max-records` | Maximum unique listings in this batch | No limit |
| `--delay` | Delay in seconds between requests | `1.5` |
| `--details` | Fetch each listing's detail page | Off |
| `--output` | JSON file to create or update | `listings.json` |

`--details` makes extra requests—typically one per listing—so it takes longer
and should be used thoughtfully.

## Output and data handling

The output is a JSON array. Each object can include:

- **Identity:** `property_id`, `title`, `url`, `listing_type`
- **Price:** `currency`, `sale_price_usd`, `rent_price_usd`, `rent_period`,
  `rent_price_usd_monthly`
- **Property:** `property_type`, `bedrooms`, `bathrooms`, `floor_area_sqm`,
  `land_area_sqm`, `floor_number`, `furnished`, `property_condition`,
  `parking_spaces`, `title_type`, `amenities`, `features`
- **Location:** `address`, `commune`, `district`, `province`, `latitude`,
  `longitude`
- **Collection metadata:** `listing_status`, `collected_at`

Unavailable values are `null`. Amenities and features are arrays. Coordinates
come from the listing and may be approximate. Commune, district, and province
are inferred from the displayed address and may be incomplete; retain the
original `address` for reference. A rent amount is normalized to
`rent_price_usd_monthly` only when the listing's period is recognized.

The same property can have separate rows for different listing types (for
example, sale and rent). If a property is scraped again with the same ID and
listing type, the original saved row is preserved; the new scrape does not
replace it. Newly encountered property/type pairs are added. This is not a
historical record of price changes.

## Tests

Run the scraper's tests from the project folder:

```powershell
python -m unittest -v test_scraper.py
```

## Responsible use

Before scraping, review Realestate.com.kh's terms, `robots.txt`, and any
applicable laws and data-use requirements. Use a modest request rate, avoid
parallel scraping, and stop if the site returns rate-limit, blocking, or other
repeated errors. Do not attempt to bypass access controls or IP restrictions.

This repository provides a scraper, not permission to reuse the website's
content. Confirm you have the right to collect, store, analyze, and redistribute
any resulting data before using it in a public project.

## GitHub note

Scraped JSON files can be large and may contain data you do not have permission
to redistribute. Keep generated datasets and your virtual environment out of
public commits unless you have reviewed both the data rights and repository
requirements. The supplied `.gitignore` excludes local environments, cache
files, and generated listing JSON files by default.
