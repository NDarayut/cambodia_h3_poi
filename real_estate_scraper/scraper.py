"""Scrape model-oriented property listings from realestate.com.kh."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

BASE_URL = "https://www.realestate.com.kh"
NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
LISTING_URL_RE = re.compile(
    r'href=["\']([^"\']*/(?:buy|rent|new-developments|boreys)/[^"\']+)["\']',
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class Listing:
    property_id: str | None = None
    title: str | None = None
    url: str | None = None
    listing_type: str | None = None
    property_type: str | None = None
    currency: str = "USD"
    sale_price_usd: float | None = None
    rent_price_usd: float | None = None
    rent_period: str | None = None
    rent_price_usd_monthly: float | None = None
    bedrooms: float | None = None
    bathrooms: float | None = None
    floor_area_sqm: float | None = None
    land_area_sqm: float | None = None
    floor_number: float | None = None
    furnished: bool | None = None
    property_condition: str | None = None
    parking_spaces: float | None = None
    title_type: str | None = None
    amenities: list[str] | None = None
    features: list[str] | None = None
    address: str | None = None
    commune: str | None = None
    district: str | None = None
    province: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    listing_status: str | None = None
    collected_at: str | None = None


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    matches = NUMBER_RE.findall(text)
    if len(matches) != 1:
        return None
    try:
        return float(matches[0])
    except ValueError:
        return None


def _money(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace(",", "")
    if not text or text in {"poa", "price on application"}:
        return None
    if re.search(r"/\s*(?:m2|m²|sqm)(?:\b|$)|per\s+(?:m2|m²|sqm)", text):
        return None
    return _number(text)


def _monthly_rent(amount: float | None, period: str | None) -> float | None:
    if amount is None or not period:
        return None
    normalized = period.lower().strip().replace(" ", "")
    if any(token in normalized for token in ("/mo", "month", "monthly")):
        return amount
    if any(token in normalized for token in ("/week", "weekly")):
        return amount * 52 / 12
    if any(token in normalized for token in ("/day", "daily")):
        return amount * 365 / 12
    if any(token in normalized for token in ("/year", "yearly", "annual")):
        return amount / 12
    return None


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _next_data(html: str) -> dict[str, Any]:
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise ValueError("The page did not contain a __NEXT_DATA__ payload")
    return json.loads(match.group(1))


def _is_listing(record: dict[str, Any]) -> bool:
    return any(
        key in record
        for key in (
            "propertyId",
            "listingId",
            "addressLatitude",
            "addressLongitude",
            "listingType",
        )
    ) and any(key in record for key in ("title", "headline", "propertyType", "price", "address"))


def _listing_url(record: dict[str, Any]) -> str | None:
    value = _first(record, "url", "href", "link", "listingUrl", "propertyUrl")
    if isinstance(value, dict):
        value = _first(value, "url", "href")
    if not isinstance(value, str) or not value:
        return None
    return urljoin(BASE_URL, value)


def _location_parts(address: str | None) -> tuple[str | None, str | None, str | None]:
    if not address:
        return None, None, None
    parts = [part.strip() for part in address.split(",") if part.strip()]
    if len(parts) >= 3:
        return parts[-3], parts[-2], parts[-1]
    if len(parts) == 2:
        return None, parts[-2], parts[-1]
    return None, None, parts[0] if parts else None


def _specification_values(record: dict[str, Any]) -> dict[str, Any]:
    specifications = record.get("specifications")
    details = (
        specifications.get("detail", [])
        if isinstance(specifications, dict)
        else []
    )
    values = {}
    for item in details:
        if isinstance(item, dict) and item.get("type"):
            values[item["type"]] = item.get("shortLabel") or item.get("label")
    return values


def normalize_listing(record: dict[str, Any]) -> Listing:
    spec = _specification_values(record)
    listing_type = str(
        _first(record, "listingType", "offerType", "transactionType") or ""
    ).lower()
    sale_display = _first(record, "salePrice", "displayPrice", "price", "priceValue")
    rent_display = _first(record, "rentPrice", "displayRent", "rent")
    if not rent_display and "rent" in listing_type:
        rent_display = sale_display
    sale_price = (
        _money(sale_display)
        if "sale" in listing_type or listing_type == "both"
        else None
    )
    rent_price = (
        _money(rent_display)
        if "rent" in listing_type or listing_type == "both"
        else None
    )
    rent_period = _first(record, "rentPeriod", "rent_period")
    address = _first(record, "address", "location")
    commune, district, province = _location_parts(address)

    return Listing(
        property_id=(
            str(_first(record, "propertyId", "listingId", "id"))
            if _first(record, "propertyId", "listingId", "id") is not None
            else None
        ),
        title=_first(record, "title", "headline", "name"),
        url=_listing_url(record),
        listing_type=listing_type or None,
        property_type=_first(record, "propertyType", "categoryName", "type"),
        sale_price_usd=sale_price,
        rent_price_usd=rent_price,
        rent_period=rent_period,
        rent_price_usd_monthly=_monthly_rent(rent_price, rent_period),
        bedrooms=_number(
            _first(record, "bedrooms", "bedroom", "bedroomsCount")
            or spec.get("bedrooms")
        ),
        bathrooms=_number(
            _first(record, "bathrooms", "bathroom", "bathroomsCount")
            or spec.get("bathrooms")
        ),
        floor_area_sqm=_number(
            _first(record, "floorArea", "floorAreaSqm", "floorSize")
            or spec.get("floor_area")
        ),
        land_area_sqm=_number(
            _first(record, "landArea", "landAreaSqm") or spec.get("land_area")
        ),
        floor_number=_number(
            _first(record, "floorNumber", "floorLevel")
            or spec.get("floor_level")
        ),
        address=address.strip() if isinstance(address, str) else address,
        commune=_first(record, "commune", "sangkat") or commune,
        district=_first(record, "district", "khan") or district,
        province=_first(record, "province", "city") or province,
        latitude=_number(
            _first(record, "addressLatitude", "latitude", "lat")
        ),
        longitude=_number(
            _first(record, "addressLongitude", "longitude", "lng", "lon")
        ),
        listing_status=_first(record, "status", "listingStatus"),
        collected_at=datetime.now(timezone.utc).isoformat(),
    )


def _set_page(url: str, page: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _listing_key(listing: Listing) -> str:
    identity = listing.property_id or listing.url or listing.title
    return f"{identity}|{listing.listing_type or 'unknown'}"


def _record_key(record: dict[str, Any]) -> tuple[str, str] | None:
    identity = record.get("property_id") or record.get("url") or record.get("title")
    if not identity:
        return None
    return (
        str(identity),
        str(record.get("listing_type") or "unknown"),
    )


def add_new_listings(output_path: Path, listings: list[Listing]) -> tuple[int, int]:
    """Add unseen property/type records without changing records already saved."""
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(existing, list) or any(
            not isinstance(record, dict) for record in existing
        ):
            raise ValueError(f"{output_path} must contain a JSON array of objects")
    else:
        existing = []

    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for record in existing:
        key = _record_key(record)
        if key is None:
            continue
        previous = by_key.get(key)
        if previous is None or str(record.get("collected_at") or "") >= str(
            previous.get("collected_at") or ""
        ):
            by_key[key] = record

    incoming_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for listing in listings:
        record = asdict(listing)
        key = _record_key(record)
        if key is None:
            raise ValueError("Each scraped record needs a property identity")
        if key not in incoming_by_key:
            incoming_by_key[key] = record

    inserted = 0
    already_saved = 0
    for key, record in incoming_by_key.items():
        if key in by_key:
            already_saved += 1
        else:
            inserted += 1
            by_key[key] = record

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(list(by_key.values()), ensure_ascii=False, indent=2) + "\n"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(payload)
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return inserted, already_saved


def _detail_record(html: str, listing: Listing) -> Listing:
    root = _next_data(html)
    page_props = root.get("props", {}).get("pageProps", {})
    cache_data = page_props.get("cacheData", {})
    detail = cache_data.get("listing", {}).get("data", {})
    if not isinstance(detail, dict) or not detail:
        raise ValueError(f"Could not find detail data for {listing.url}")

    header = detail.get("header", {})
    main = detail.get("mainContent", {})
    badges = detail.get("badges", [])
    values: dict[str, Any] = {}
    for badge in badges:
        if not isinstance(badge, dict):
            continue
        label = str(badge.get("label", "")).lower()
        value = badge.get("displayValue")
        if "bedroom" in label:
            values["bedrooms"] = value
        elif "bathroom" in label:
            values["bathrooms"] = value
        elif "floor area" in label:
            values["floorArea"] = value
        elif "land area" in label:
            values["landArea"] = value
        elif "floor" in label:
            values["floorNumber"] = value
        elif "parking" in label:
            values["parkingSpaces"] = value
        elif "facing" in label:
            values["facing"] = value

    features: list[str] = []
    amenities: list[str] = []
    title_type = None
    property_type = None
    furnished: bool | None = None
    property_condition = None
    for section in detail.get("features", []):
        if not isinstance(section, dict):
            continue
        section_name = str(section.get("headline", "")).lower()
        for item in section.get("items", []):
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            if not isinstance(label, str):
                continue
            if section_name == "property overview":
                if label.lower().startswith("title:"):
                    title_type = label.split(":", 1)[1].strip()
                if label.lower().startswith("property type:"):
                    property_type = label.split(":", 1)[1].strip()
            elif section_name == "property features":
                features.append(label)
                lower_label = label.lower()
                if "furnished" in lower_label:
                    furnished = not lower_label.startswith("not ")
                    if "unfurnished" in lower_label:
                        furnished = False
                if "condition:" in lower_label:
                    property_condition = label.split(":", 1)[1].strip()
            elif section_name in {"amenities", "security"}:
                amenities.append(label)

    existing = asdict(listing)
    record = {
        **existing,
        "title": _first(main, "headline") or _first(header, "headline") or listing.title,
        "listingType": _first(header, "listingType") or listing.listing_type,
        "salePrice": _first(header, "salePrice"),
        "rentPrice": _first(header, "rentPrice"),
        "rentPeriod": _first(header, "rentPeriod"),
        "address": _first(header, "address") or listing.address,
        "bedrooms": values.get("bedrooms"),
        "bathrooms": values.get("bathrooms"),
        "floorArea": values.get("floorArea"),
        "landArea": values.get("landArea"),
        "floorNumber": values.get("floorNumber"),
        "parkingSpaces": values.get("parkingSpaces"),
        "propertyType": property_type,
        "status": _first(header, "status") or listing.listing_status,
    }
    normalized = normalize_listing(record)
    values_out = asdict(listing)
    for key, value in asdict(normalized).items():
        if value not in (None, "", []):
            values_out[key] = value
    values_out.update(
        {
            "title_type": title_type,
            "furnished": furnished,
            "property_condition": property_condition,
            "parking_spaces": _number(values.get("parkingSpaces")),
            "amenities": amenities,
            "features": features,
        }
    )
    return Listing(**values_out)


class RealEstateScraper:
    def __init__(self, delay: float = 1.5, timeout: float = 30.0) -> None:
        self.delay = delay
        self.timeout = timeout

    def fetch(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "realestate-kh-research-scraper/1.0 "
                    "(respectful rate-limited data collection)"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8")

    def parse_page(self, html: str) -> list[Listing]:
        data = _next_data(html)
        records = [record for record in _walk_dicts(data) if _is_listing(record)]
        unique: dict[str, Listing] = {}
        for record in records:
            listing = normalize_listing(record)
            key = listing.property_id or listing.url or listing.title
            if key:
                unique[str(key)] = listing

        fallback_urls = [
            urljoin(BASE_URL, url) for url in LISTING_URL_RE.findall(html)
        ]
        for listing, url in zip(
            [item for item in unique.values() if item.url is None], fallback_urls
        ):
            listing.url = url
        return list(unique.values())

    def scrape_page(
        self,
        start_url: str,
        page: int,
        details: bool = False,
    ) -> list[Listing]:
        listings = self.parse_page(self.fetch(_set_page(start_url, page)))
        if details:
            enriched = []
            for index, listing in enumerate(listings):
                if listing.url:
                    if index:
                        time.sleep(self.delay)
                    listing = _detail_record(self.fetch(listing.url), listing)
                enriched.append(listing)
            listings = enriched
        return listings


def scrape_batch(
    scraper: RealEstateScraper,
    start_url: str,
    start_page: int,
    page_count: int,
    output_path: Path,
    max_records: int | None = None,
    details: bool = False,
) -> tuple[int, int]:
    """Scrape and persist each page, returning unique records and pages saved."""
    collected_at = datetime.now(timezone.utc).isoformat()
    seen_this_run: set[str] = set()
    records_saved = 0
    pages_saved = 0

    for page in range(start_page, start_page + page_count):
        if pages_saved:
            time.sleep(scraper.delay)
        listings = scraper.scrape_page(start_url, page, details)
        if not listings:
            print(f"Page {page} returned no listings; stopping this batch.")
            break

        page_listings: dict[str, Listing] = {}
        for listing in listings:
            key = _listing_key(listing)
            if key not in seen_this_run:
                page_listings[key] = listing

        remaining = (
            max_records - len(seen_this_run)
            if max_records is not None
            else None
        )
        if remaining is not None:
            page_listings = dict(list(page_listings.items())[:remaining])
        for key, listing in page_listings.items():
            listing.collected_at = collected_at
            seen_this_run.add(key)

        inserted, already_saved = add_new_listings(
            output_path, list(page_listings.values())
        )
        saved = inserted
        records_saved += saved
        pages_saved += 1
        print(
            f"Saved page {page}: {len(page_listings)} unique listings "
            f"({inserted} new, {already_saved} already saved and kept unchanged; "
            f"{len(seen_this_run)} in this run)."
        )

        if max_records is not None and len(seen_this_run) >= max_records:
            print(f"Reached the --max-records limit of {max_records}.")
            break
        if len(listings) < 10:
            print("Page contained fewer than 10 listings; stopping this batch.")
            break

    return records_saved, pages_saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=f"{BASE_URL}/buy/")
    parser.add_argument(
        "--start-page", type=int, default=1,
        help="First search-results page to scrape (default: 1).",
    )
    parser.add_argument(
        "--pages", type=int, default=1,
        help="Number of consecutive pages to scrape and save (default: 1).",
    )
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument(
        "--details",
        action="store_true",
        help="Fetch detail pages for title, amenities, title type, and other fields.",
    )
    parser.add_argument("--output", default="listings.json")
    args = parser.parse_args()
    if args.start_page < 1 or args.pages < 1 or args.delay < 0 or (
        args.max_records is not None and args.max_records < 1
    ):
        parser.error(
            "--start-page, --pages, and --max-records must be positive; "
            "--delay cannot be negative"
        )

    records_saved, pages_saved = scrape_batch(
        RealEstateScraper(delay=args.delay),
        args.url,
        args.start_page,
        args.pages,
        Path(args.output),
        args.max_records,
        args.details,
    )
    print(
        f"Batch finished: saved {pages_saved} pages and added "
        f"{records_saved} new properties to {args.output}."
    )


if __name__ == "__main__":
    main()
