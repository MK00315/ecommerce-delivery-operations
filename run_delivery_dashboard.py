"""Start the local Delivery Ops dashboard without changing training/cloud artifacts."""
import argparse
from pathlib import Path

import uvicorn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8125)
    parser.add_argument("--check", action="store_true", help="Verify the snapshot and dashboard imports, without starting a server")
    settings = parser.parse_args()
    root = Path(__file__).resolve().parent
    if not (root / "data/dashboard/snapshot_manifest.json").is_file():
        from build_dashboard_data import build
        build()
    import delivery_dashboard
    if settings.check:
        print(delivery_dashboard.health())
        assert delivery_dashboard.metadata()["source_orders"] == 99441
        assert delivery_dashboard.view_data("ALL", None, None)["metrics"]["orders"] == 99441
        print("Delivery dashboard readiness passed.")
        return
    print(f"Delivery Ops local preview: http://127.0.0.1:{settings.port}", flush=True)
    uvicorn.run(delivery_dashboard.app, host="127.0.0.1", port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
