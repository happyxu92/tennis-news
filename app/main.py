from __future__ import annotations

import argparse
import asyncio

from app.crawler.service import CrawlerService
from app.logging import configure_logging, get_logger
from app.services.diff_service import DiffService
from app.settings import get_settings
from app.storage import create_engine_from_settings, create_session_factory, init_database

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tennis news automation entrypoint")
    parser.add_argument("command", choices=["init-db", "sync"], help="Command to execute")
    return parser


async def run_async(command: str) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = create_engine_from_settings(settings)
    init_database(engine)
    session_factory = create_session_factory(engine)

    if command == "init-db":
        logger.info("database initialized")
        return

    with session_factory() as session:
        crawler = CrawlerService(settings=settings, session=session)
        await crawler.sync_all()
        diff_service = DiffService(settings=settings, session=session)
        diff_service.detect_and_queue_jobs()


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(run_async(args.command))


if __name__ == "__main__":
    main()
