"""Independent source reconciliations and important date/geography boundaries."""
from decimal import Decimal
import json
from pathlib import Path
import sys

import duckdb
import pandas as pd
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from delivery_pipeline import sha256


@pytest.fixture(scope="module")
def connection():
    database = ROOT / "data/interim/delivery_operations.duckdb"
    assert database.exists(), "Run delivery_pipeline.py before the full-data integration checks."
    client = duckdb.connect(str(database), read_only=True)
    yield client
    client.close()


@pytest.fixture(scope="module")
def macros():
    client = duckdb.connect()
    source = (ROOT / "sql/01_clean.sql").read_text(encoding="utf-8")
    client.execute(source.split("CREATE OR REPLACE TABLE silver.postcodes")[0])
    yield client
    client.close()


@pytest.mark.parametrize("promised,arrived,expected", [
    ("2018-01-10 00:00:00", "2018-01-10 23:59:59", False),
    ("2018-01-10 00:00:00", "2018-01-11 00:00:00", True),
    ("2018-01-10 00:00:00", "2018-01-09 09:00:00", False),
    (None, "2018-01-10 12:00:00", None),
    ("2018-01-10 00:00:00", None, None),
])
def test_promised_date_is_an_inclusive_calendar_day(macros, promised, arrived, expected):
    actual = macros.execute("SELECT sla_late(?::TIMESTAMP, ?::TIMESTAMP)", [promised, arrived]).fetchone()[0]
    assert actual is expected


@pytest.mark.parametrize("value,expected", [("123", "00123"), ("01001", "01001"), (" 12345 ", "12345"), ("123456", None), ("AB123", None), (None, None)])
def test_postcodes_preserve_leading_zeroes(macros, value, expected):
    assert macros.execute("SELECT postcode(?::VARCHAR)", [value]).fetchone()[0] == expected


def test_missing_coordinates_stay_unknown(macros):
    assert macros.execute("SELECT great_circle_km(NULL, -46.6, -23.5, -46.6)").fetchone()[0] is None
    assert macros.execute("SELECT great_circle_km(-23.5, -46.6, -23.5, -46.6)").fetchone()[0] == pytest.approx(0)
    # One degree on the equator is about 111.2 km, not a road-route distance.
    assert macros.execute("SELECT great_circle_km(0.0, 0.0, 0.0, 1.0)").fetchone()[0] == pytest.approx(111.195, abs=0.01)


def test_order_grain_and_all_source_ids_are_preserved(connection):
    orders = pd.read_csv(ROOT / "data/raw/olist-v2/olist_orders_dataset.csv", usecols=["order_id"])
    fact = connection.execute("SELECT order_id FROM gold.orders").df()
    assert len(fact) == len(orders) == 99441
    assert fact.order_id.is_unique and set(fact.order_id) == set(orders.order_id)
    assert connection.execute("SELECT count(*) FROM gold.order_items").fetchone()[0] == 112650


def test_money_is_reconciled_in_integer_cents(connection):
    folder = ROOT / "data/raw/olist-v2"
    for file, column, output in [("olist_order_items_dataset.csv", "price", "item_value"),
                                  ("olist_order_items_dataset.csv", "freight_value", "freight_value"),
                                  ("olist_order_payments_dataset.csv", "payment_value", "recorded_payment_value")]:
        source = pd.read_csv(folder / file, usecols=[column], dtype="string")
        independent = sum((Decimal(value) for value in source[column].dropna()), Decimal("0"))
        actual = connection.execute(f"SELECT sum({output}) FROM gold.orders").fetchone()[0]
        assert isinstance(actual, Decimal) and actual == independent


def test_lateness_matches_independent_pandas_dates(connection):
    source = pd.read_csv(ROOT / "data/raw/olist-v2/olist_orders_dataset.csv")
    arrived = pd.to_datetime(source.order_delivered_customer_date)
    promised = pd.to_datetime(source.order_estimated_delivery_date)
    purchased = pd.to_datetime(source.order_purchase_timestamp)
    eligible = source.order_status.eq("delivered") & arrived.notna() & promised.notna() & purchased.notna()
    eligible &= arrived.ge(purchased) & promised.dt.normalize().ge(purchased.dt.normalize())
    late = arrived.dt.normalize().gt(promised.dt.normalize()) & eligible
    expected = set(source.loc[late, "order_id"])
    actual = set(connection.execute("SELECT order_id FROM gold.orders WHERE is_late").df().order_id)
    assert actual == expected and int(eligible.sum()) == 96470 and len(actual) == 6534
    assert connection.execute("SELECT count(*) FROM gold.orders WHERE NOT sla_eligible AND is_late IS NOT NULL").fetchone()[0] == 0


def test_review_id_reuse_does_not_delete_other_orders(connection):
    source = pd.read_csv(ROOT / "data/raw/olist-v2/olist_order_reviews_dataset.csv", usecols=["order_id", "review_id"])
    assert source.review_id.duplicated().sum() == 814
    assert source.duplicated(["order_id", "review_id"]).sum() == 0
    assert connection.execute("SELECT count(*) FROM silver.reviews").fetchone()[0] == len(source)
    assert connection.execute("SELECT count(*) FROM silver.latest_reviews").fetchone()[0] == source.order_id.nunique()


def test_geolocation_centroid_matches_source_median(connection):
    source = pd.read_csv(ROOT / "data/raw/olist-v2/olist_geolocation_dataset.csv", dtype={"geolocation_zip_code_prefix": "string"})
    valid = source.geolocation_lat.between(-34, 6) & source.geolocation_lng.between(-74, -34)
    assert int((~valid).sum()) == 42
    source = source.loc[valid].copy()
    source["prefix"] = source.geolocation_zip_code_prefix.str.zfill(5)
    grouped = source.groupby("prefix")[["geolocation_lat", "geolocation_lng"]].median()
    actual = connection.execute("SELECT postcode_prefix, latitude, longitude FROM silver.postcodes").df().set_index("postcode_prefix").sort_index()
    grouped = grouped.sort_index()
    assert list(actual.index) == list(grouped.index)
    assert actual.latitude.to_numpy() == pytest.approx(grouped.geolocation_lat.to_numpy(), abs=1e-10)
    assert actual.longitude.to_numpy() == pytest.approx(grouped.geolocation_lng.to_numpy(), abs=1e-10)


def test_parquet_exports_match_the_verified_database(connection):
    summary = json.loads((ROOT / "reports/latest_run.json").read_text())
    manifest = json.loads((ROOT / summary["run_directory"] / "processed_manifest.json").read_text())
    assert len(manifest) == 8
    for entry in manifest:
        path = ROOT / entry["file"]
        assert pq.ParquetFile(path).metadata.num_rows == entry["rows"]
        assert sha256(path) == entry["sha256"]
        assert connection.execute(f"SELECT count(*) FROM {entry['table']}").fetchone()[0] == entry["rows"]


def test_monthly_report_reconciles_and_quality_controls_pass(connection):
    summary = json.loads((ROOT / "reports/latest_run.json").read_text())
    run = ROOT / summary["run_directory"]
    monthly = pd.read_csv(run / "sql/monthly_delivery.csv")
    assert monthly.orders.sum() == 99441 and monthly.eligible_orders.sum() == 96470
    assert monthly.late_orders.sum() == 6534
    quality = json.loads((run / "data_quality.json").read_text())
    assert quality["passed"] and not any(quality["orphan_rows"].values())
    assert summary["analysis_count"] == 12 and summary["model_training"] is False
