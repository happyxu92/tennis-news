from __future__ import annotations

import argparse
import asyncio

from app.logging import configure_logging, get_logger
from app.services.dispatch_service import DispatchService
from app.services.scheduler_service import SchedulerService
from app.services.sync_service import SyncService
from app.settings import get_settings
from app.storage import create_engine_from_settings, create_session_factory, init_database

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tennis news automation entrypoint")
    parser.add_argument(
        "command",
        choices=[
            "init-db",
            "sync",
            "publish-pending",
            "check-publish-status",
            "run-scheduler",
        ],
        help="Command to execute",
    )
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

    if command == "run-scheduler":
        scheduler_service = SchedulerService(
            settings=settings,
            session_factory=session_factory,
        )
        try:
            await scheduler_service.run_forever()
        finally:
            scheduler_service.shutdown()
        return

    with session_factory() as session:
        if command == "sync":
            sync_service = SyncService(settings=settings, session=session)
            await sync_service.run_once()
            return

        dispatch_service = DispatchService(settings=settings, session=session)
        try:
            if command == "publish-pending":
                await dispatch_service.dispatch_pending_jobs()
            elif command == "check-publish-status":
                await dispatch_service.sync_publishing_jobs()
        finally:
            await dispatch_service.aclose()


def main() -> None:
    args = build_parser().parse_args()
    try:
        asyncio.run(run_async(args.command))
    except KeyboardInterrupt:
        logger.info("shutdown requested")


if __name__ == "__main__":
    main()
