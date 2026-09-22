"""One-time, idempotent classification of verified legacy Drive inventories.

Run with the production DATABASE_URL after deploying the explicit-health-tag
change. Runtime health checks never infer exclusions from these paths; this is
the auditable bridge for assets imported before that rule existed.
"""

import json
import os

from sqlalchemy import create_engine, text


CLASSIFICATIONS = (
    ("Commercial Insurance - LEGACY IMAGES/%", "legacy_image_library"),
    ("Commercial Insurance Master - Abel/%", "historical_legacy_import"),
    ("%/Original User Supplied Images%", "original_user_supplied_images"),
)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    engine = create_engine(database_url)
    with engine.connect() as read_connection:
        for folder_pattern, classification in CLASSIFICATIONS:
            rows = read_connection.execute(
                text(
                    """
                    SELECT id, soft_tags
                    FROM drive_assets
                    WHERE archived = FALSE AND folder_path ILIKE :folder_pattern
                    """
                ),
                {"folder_pattern": folder_pattern},
            ).mappings().all()
            classified = malformed = 0
            for row in rows:
                raw_tags = row["soft_tags"]
                try:
                    tags = json.loads(raw_tags) if isinstance(raw_tags, str) else (raw_tags or {})
                    tags = tags if isinstance(tags, dict) else {}
                    parseable = True
                except (TypeError, json.JSONDecodeError):
                    tags = {}
                    malformed += 1
                    parseable = False
                if tags.get("copy_health_exclusion"):
                    continue
                # Commit each row so a malformed historical record or a
                # concurrent row change cannot roll back earlier inventory.
                with engine.begin() as write_connection:
                    if parseable:
                        # Mutate only this one JSON key in PostgreSQL. This
                        # preserves concurrent copy-sync metadata writes.
                        result = write_connection.execute(
                            text(
                                """
                                UPDATE drive_assets
                                SET soft_tags = jsonb_set(
                                    CASE
                                        WHEN soft_tags IS NULL OR btrim(soft_tags) = '' THEN '{}'::jsonb
                                        ELSE soft_tags::jsonb
                                    END,
                                    '{copy_health_exclusion}',
                                    to_jsonb(CAST(:classification AS text)), true
                                )
                                WHERE id = :id
                                  AND COALESCE(NULLIF(soft_tags, '')::jsonb ->> 'copy_health_exclusion', '') = ''
                                """
                            ),
                            {"id": row["id"], "classification": classification},
                        )
                    else:
                        # Invalid JSON cannot be key-mutated. Replace it only
                        # if no concurrent process has changed the exact raw
                        # value we inspected; otherwise leave it untouched.
                        result = write_connection.execute(
                            text(
                                """
                                UPDATE drive_assets
                                SET soft_tags = CAST(:replacement AS jsonb)
                                WHERE id = :id AND soft_tags IS NOT DISTINCT FROM :original
                                """
                            ),
                            {
                                "id": row["id"], "original": raw_tags,
                                "replacement": json.dumps({"copy_health_exclusion": classification}),
                            },
                        )
                classified += result.rowcount
            print(f"{classification}: {classified} classified ({malformed} malformed tag(s) normalized)")


if __name__ == "__main__":
    main()
