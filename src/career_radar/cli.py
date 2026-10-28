import argparse
import json
import logging

from career_radar.config import Settings
from career_radar.db import make_engine
from career_radar.ingestion import configure_source, run_ingestion


def positive(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="CareerRadar manual ingestion")
    sub = parser.add_subparsers(dest="command", required=True)
    source = sub.add_parser("source-init", help="Record reviewed policy and source configuration")
    source.add_argument("--enable", action="store_true")
    ingest = sub.add_parser("ingest")
    ingest.add_argument(
        "--test-run", action="store_true", help="One query, two pages, four requests"
    )
    ingest.add_argument("--max-queries", type=positive)
    ingest.add_argument("--max-pages", type=positive)
    ingest.add_argument("--max-requests", type=positive)
    args = parser.parse_args()
    settings = Settings()
    engine = make_engine(settings)
    logging.basicConfig(level=logging.INFO)
    try:
        if args.command == "source-init":
            source_row = configure_source(engine, args.enable)
            print(json.dumps({"source": source_row.name, "status": source_row.status}))
            return 0
        updates = {
            key: getattr(args, key)
            for key in ("max_queries", "max_pages", "max_requests")
            if getattr(args, key) is not None
        }
        if args.test_run:
            updates.update(max_queries=1, max_pages=2, max_requests=4, verification_budget=0)
        settings = Settings.model_validate({**settings.model_dump(), **updates})
        summary = run_ingestion(engine, settings)
        print(json.dumps(summary))
        return {"success": 0, "partial": 2, "failed": 1}[summary["status"]]
    except Exception as exc:
        # Exceptions from DB/HTTP libraries can contain credentials or raw payloads.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": type(exc).__name__,
                    "message": "Check source policy, polling interval, and database readiness",
                }
            )
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
