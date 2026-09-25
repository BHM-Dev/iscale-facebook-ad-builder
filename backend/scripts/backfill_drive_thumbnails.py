"""One-time backfill of thumbnail_r2_key for Drive assets synced before real
grid thumbnails existed.

thumbnail_r2_key was always written as NULL until this change — every row
synced before it will keep loading full-res images in the library grid
forever unless backfilled here. New/changed Drive files get a real thumbnail
automatically going forward via DriveSyncService; this script only needs to
run once against the existing backlog.

Run inside the backend container (no local venv on the VPS):
    docker exec -it <backend-container> python backend/scripts/backfill_drive_thumbnails.py
"""

import io
import os

import requests
from sqlalchemy import create_engine, text

from app.services.drive_sync_service import DriveSyncService


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    engine = create_engine(database_url)

    # DriveSyncService only needs its thumbnail/upload helpers here — no Drive
    # API client, no DB session of its own (this script owns its own engine so
    # each row commits independently, same reasoning as the copy-health backfill).
    service = DriveSyncService.__new__(DriveSyncService)

    with engine.connect() as read_connection:
        rows = read_connection.execute(
            text(
                """
                SELECT id, r2_key, file_name
                FROM drive_assets
                WHERE format = 'image' AND archived = FALSE AND thumbnail_r2_key IS NULL
                """
            )
        ).mappings().all()

    generated = failed = 0
    for row in rows:
        try:
            response = requests.get(row["r2_key"], timeout=30)
            response.raise_for_status()
            thumbnail_r2_key = service._upload_image_thumbnail(response.content, "image")
        except Exception as exc:
            failed += 1
            print(f"skip {row['file_name']} ({row['id']}): {exc}")
            continue
        if thumbnail_r2_key is None:
            failed += 1
            print(f"skip {row['file_name']} ({row['id']}): thumbnail generation returned nothing")
            continue
        with engine.begin() as write_connection:
            write_connection.execute(
                text("UPDATE drive_assets SET thumbnail_r2_key = :thumbnail_r2_key WHERE id = :id"),
                {"id": row["id"], "thumbnail_r2_key": thumbnail_r2_key},
            )
        generated += 1

    print(f"Backfilled {generated} thumbnail(s), {failed} skipped, out of {len(rows)} candidate row(s).")


if __name__ == "__main__":
    main()
