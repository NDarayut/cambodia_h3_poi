import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from scraper import (
    Listing,
    _detail_record,
    _money,
    normalize_listing,
    scrape_batch,
    add_new_listings,
)


class NormalizeListingTests(unittest.TestCase):
    def test_sale_listing_converts_model_fields(self):
        listing = normalize_listing(
            {
                "id": 42,
                "headline": "Condo for sale",
                "listingType": "sale",
                "categoryName": "Condo",
                "displayPrice": "$157,000",
                "address": "BKK 1, Boeng Keng Kang, Phnom Penh",
                "addressLatitude": 11.55,
                "addressLongitude": 104.92,
                "specifications": {
                    "detail": [
                        {"type": "floor_area", "shortLabel": "61m²"},
                        {"type": "floor_level", "shortLabel": "10"},
                    ]
                },
            }
        )

        self.assertEqual(listing.property_id, "42")
        self.assertEqual(listing.sale_price_usd, 157000)
        self.assertIsNone(listing.rent_price_usd)
        self.assertEqual(listing.floor_area_sqm, 61)
        self.assertEqual(listing.floor_number, 10)
        self.assertEqual(listing.commune, "BKK 1")
        self.assertEqual(listing.district, "Boeng Keng Kang")
        self.assertEqual(listing.province, "Phnom Penh")
        self.assertEqual(listing.latitude, 11.55)

    def test_rent_price_is_normalized_when_period_is_known(self):
        listing = normalize_listing(
            {
                "id": 7,
                "listingType": "rent",
                "displayRent": "$1,000",
                "rentPeriod": "/mo",
            }
        )

        self.assertEqual(listing.rent_price_usd, 1000)
        self.assertEqual(listing.rent_price_usd_monthly, 1000)
        self.assertIsNone(listing.sale_price_usd)

    def test_ranges_and_price_per_area_are_not_total_values(self):
        self.assertIsNone(_money("$740/m²"))
        self.assertIsNone(_money("$100,000 - $200,000"))
        self.assertIsNone(normalize_listing({"listingType": "sale", "price": "67 to 180m²"}).sale_price_usd)

    def test_detail_page_enriches_listing_features_and_prices(self):
        data = {
            "props": {
                "pageProps": {
                    "cacheData": {
                        "listing": {
                            "data": {
                                "header": {
                                    "listingType": "both",
                                    "salePrice": "$300,000",
                                    "rentPrice": "$8,500",
                                    "rentPeriod": "/mo",
                                    "address": "Veal Sbov, Chbar Ampov, Phnom Penh",
                                    "status": "current",
                                },
                                "mainContent": {
                                    "headline": "Luxury villa",
                                    "description": "A test description",
                                },
                                "badges": [
                                    {"label": "Bedroom", "displayValue": "6"},
                                    {"label": "Land Area (m²)", "displayValue": "1890"},
                                ],
                                "features": [
                                    {
                                        "headline": "Property Overview",
                                        "items": [
                                            {"label": "Title: Hard Title"},
                                            {"label": "Property type: Villa"},
                                        ],
                                    },
                                    {
                                        "headline": "Property Features",
                                        "items": [{"label": "Fully Furnished"}],
                                    },
                                    {
                                        "headline": "Amenities",
                                        "items": [{"label": "Swimming Pool"}],
                                    },
                                ],
                            }
                        }
                    }
                }
            }
        }
        listing = _detail_record(
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data)
            + "</script>",
            Listing(property_id="1", url="https://example.com/listing"),
        )

        self.assertEqual(listing.sale_price_usd, 300000)
        self.assertEqual(listing.rent_price_usd_monthly, 8500)
        self.assertEqual(listing.bedrooms, 6)
        self.assertEqual(listing.land_area_sqm, 1890)
        self.assertEqual(listing.title_type, "Hard Title")
        self.assertTrue(listing.furnished)
        self.assertIn("Swimming Pool", listing.amenities)
        self.assertNotIn("description", asdict(listing))
        self.assertNotIn("listed_date", asdict(listing))
        self.assertNotIn("agency", asdict(listing))
        self.assertNotIn("phone", asdict(listing))
        self.assertNotIn("images", asdict(listing))


class UniqueListingTests(unittest.TestCase):
    def test_add_new_listings_keeps_existing_record_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "history.json"
            first_snapshot = Listing(
                property_id="42",
                listing_type="sale",
                sale_price_usd=150000,
                collected_at="2026-10-01T00:00:00+00:00",
            )
            changed_snapshot = Listing(
                property_id="42",
                listing_type="sale",
                sale_price_usd=145000,
                collected_at="2026-10-08T00:00:00+00:00",
            )

            self.assertEqual(
                add_new_listings(output, [first_snapshot]), (1, 0)
            )
            self.assertEqual(
                add_new_listings(output, [first_snapshot, changed_snapshot]),
                (0, 1),
            )
            records = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["sale_price_usd"], 150000)
        self.assertEqual(records[0]["collected_at"], "2026-10-01T00:00:00+00:00")

    def test_sale_and_rent_listings_are_distinct(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "history.json"
            sale = Listing(
                property_id="42",
                listing_type="sale",
                sale_price_usd=150000,
                collected_at="2026-10-01T00:00:00+00:00",
            )
            rent = Listing(
                property_id="42",
                listing_type="rent",
                rent_price_usd=900,
                collected_at="2026-10-01T00:00:00+00:00",
            )

            self.assertEqual(add_new_listings(output, [sale, rent]), (2, 0))
            records = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual({record["listing_type"] for record in records}, {"sale", "rent"})

    def test_scrape_batch_resumes_at_requested_page_and_saves_each_page(self):
        class FakeScraper:
            delay = 0

            def __init__(self):
                self.requested_pages = []

            def scrape_page(self, start_url, page, details):
                self.requested_pages.append(page)
                offset = 0 if page == 5 else 5
                return [
                    Listing(
                        property_id=str(index),
                        listing_type="sale",
                        sale_price_usd=100000 + index,
                    )
                    for index in range(offset, offset + 10)
                ]

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "history" / "sale.json"
            fake_scraper = FakeScraper()

            records_added, pages_saved = scrape_batch(
                fake_scraper,
                "https://example.com/buy/",
                start_page=5,
                page_count=2,
                output_path=output,
            )
            records = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(fake_scraper.requested_pages, [5, 6])
        self.assertEqual(pages_saved, 2)
        self.assertEqual(records_added, 15)
        self.assertEqual(len(records), 15)
        self.assertEqual(len({record["collected_at"] for record in records}), 1)

    def test_scrape_batch_stops_after_max_records(self):
        class FakeScraper:
            delay = 0

            def __init__(self):
                self.requested_pages = []

            def scrape_page(self, start_url, page, details):
                self.requested_pages.append(page)
                return [
                    Listing(
                        property_id=str(index),
                        listing_type="rent",
                        rent_price_usd=1000,
                    )
                    for index in range(10)
                ]

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "rent.json"
            fake_scraper = FakeScraper()
            records_added, pages_saved = scrape_batch(
                fake_scraper,
                "https://example.com/rent/",
                start_page=1,
                page_count=5,
                output_path=output,
                max_records=4,
            )
            records = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(fake_scraper.requested_pages, [1])
        self.assertEqual(pages_saved, 1)
        self.assertEqual(records_added, 4)
        self.assertEqual(len(records), 4)


if __name__ == "__main__":
    unittest.main()
