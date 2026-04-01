"""
MinIO blob archiver for audit events.

Periodically queries PostgreSQL for recent audit events and archives them
to MinIO (S3-compatible) as JSONL files.

Archive path pattern:
    audit-logs/{YYYY}/{MM}/{DD}/{HH}.jsonl

Each run covers a rolling 2-hour window. Files are overwritten on each run
(idempotent). This means MinIO always has the latest snapshot of each hour.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.audit import AuditEvent

logger = logging.getLogger(__name__)

ARCHIVE_INTERVAL_SECONDS = 300  # run every 5 minutes
ARCHIVE_WINDOW_HOURS = 2        # archive last 2 hours of events


def _get_s3_client():
    """Return a boto3 S3 client pointed at MinIO. Returns None if boto3 not available."""
    try:
        import boto3
        from botocore.client import Config as BotoConfig
        return boto3.client(
            "s3",
            endpoint_url=settings.MINIO_ENDPOINT,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            config=BotoConfig(signature_version="s3v4"),
            region_name="us-east-1",
        )
    except Exception as exc:
        logger.error("blob_archiver: cannot create S3 client — %s", exc)
        return None


def _ensure_bucket(s3) -> None:
    """Create the audit-logs bucket if it does not exist."""
    try:
        s3.head_bucket(Bucket=settings.MINIO_BUCKET)
    except Exception:
        try:
            s3.create_bucket(Bucket=settings.MINIO_BUCKET)
            logger.info("blob_archiver: created bucket '%s'", settings.MINIO_BUCKET)
        except Exception as exc:
            logger.error("blob_archiver: failed to create bucket — %s", exc)


async def _archive_window(s3, window_start: datetime, window_end: datetime) -> None:
    """Query events in [window_start, window_end) and write to MinIO."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AuditEvent)
            .where(AuditEvent.created_at >= window_start)
            .where(AuditEvent.created_at < window_end)
            .order_by(AuditEvent.created_at)
        )
        events = result.scalars().all()

    if not events:
        return

    # Serialize events as JSONL
    lines = []
    for ev in events:
        lines.append(json.dumps({
            "id": str(ev.id),
            "event_id": ev.event_id,
            "tenant_id": str(ev.tenant_id),
            "session_id": str(ev.session_id) if ev.session_id else None,
            "agent_id": str(ev.agent_id) if ev.agent_id else None,
            "event_type": ev.event_type,
            "event_data": ev.event_data,
            "prev_hash": ev.prev_hash,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }, separators=(",", ":")))
    body = "\n".join(lines).encode("utf-8")

    # Key: audit-logs/{YYYY}/{MM}/{DD}/{HH}.jsonl
    key = (
        f"audit-logs/{window_start.strftime('%Y/%m/%d/%H')}.jsonl"
    )

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: s3.put_object(
                Bucket=settings.MINIO_BUCKET,
                Key=key,
                Body=body,
                ContentType="application/x-ndjson",
            )
        )
        logger.info(
            "blob_archiver: archived %d events to s3://%s/%s",
            len(events), settings.MINIO_BUCKET, key,
        )
    except Exception as exc:
        logger.error("blob_archiver: failed to upload %s — %s", key, exc)


async def run_archiver() -> None:
    """
    Background task: archive audit events to MinIO every ARCHIVE_INTERVAL_SECONDS.
    Covers a rolling window of the last ARCHIVE_WINDOW_HOURS hours.
    """
    # Wait for MinIO to be ready before first archive run
    await asyncio.sleep(30)

    s3 = _get_s3_client()
    if s3 is None:
        logger.error("blob_archiver: no S3 client — archiver disabled")
        return

    _ensure_bucket(s3)
    logger.info("blob_archiver: started, archiving every %ds", ARCHIVE_INTERVAL_SECONDS)

    while True:
        try:
            now = datetime.now(timezone.utc)
            # Archive each hour in the window
            for h in range(ARCHIVE_WINDOW_HOURS):
                hour_start = (now - timedelta(hours=h + 1)).replace(minute=0, second=0, microsecond=0)
                hour_end = hour_start + timedelta(hours=1)
                await _archive_window(s3, hour_start, hour_end)

        except asyncio.CancelledError:
            logger.info("blob_archiver: cancelled — shutting down")
            break
        except Exception as exc:
            logger.error("blob_archiver: error in archive cycle — %s", exc, exc_info=True)

        await asyncio.sleep(ARCHIVE_INTERVAL_SECONDS)
