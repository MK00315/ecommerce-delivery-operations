# Data provenance

Source: [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), version 2, by Olist and collaborators. Kaggle lists its license as **CC BY-NC-SA 4.0**. This portfolio uses historical 2016-2018 data for noncommercial analysis; Olist does not endorse it.

The dataset was cleaned, aggregated, assigned calendar-day delivery labels, and transformed into features, experimental ranks, review selections, and report snapshots. No source orders were sampled out of the serving database. These are modified/derived artifacts, not the original dataset. Attribution, noncommercial use, and share-alike terms continue to apply to redistributed data and derivatives; see [the license](https://creativecommons.org/licenses/by-nc-sa/4.0/) and `THIRD_PARTY_NOTICES.md`.

- `dashboard/delivery_dashboard.duckdb`: compact, read-only serving snapshot, all 99,441 orders plus saved review data. Its exact SHA-256 is checked on startup.
- `dashboard/snapshot_manifest.json`: counts, source hashes, model provenance and statistical evidence.
- `raw/olist-v2/`: original nine CSV files, intentionally excluded from Git. Run `python scripts/download_dataset.py` to retrieve version 2 and verify every hash against `docs/raw_dataset_manifest.json`.
- `interim/` and `processed/`: locally rebuilt DuckDB/Parquet files, excluded from Git. Run `python delivery_pipeline.py` after downloading the source.

No customer-upload endpoint or permanently stored user submissions exist. Filter values and custom review plans remain in server memory. The app does not contact Azure or Databricks.
