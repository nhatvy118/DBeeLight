"""Minimal logging configuration."""
import logging


def setup_logging(level: int = logging.INFO) -> None:
    # force=True: gỡ handler uvicorn đã cài sẵn rồi cấu hình lại root logger.
    # Không có force, basicConfig là no-op (root vẫn ở WARNING) -> log INFO bị nuốt.
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )
    logging.getLogger().setLevel(level)
