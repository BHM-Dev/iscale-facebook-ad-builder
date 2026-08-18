# Drive Creative Sync — Claude Code Handoff

Codex implemented the service, API route, scheduler hook, dependencies, and Creative Library UI for the Google Drive creative sync pass.

## Migration Still Needed

Do not ship until Claude Code adds the Alembic migration and model wiring.

Suggested `DriveAsset` model:

```python
class DriveAsset(Base):
    __tablename__ = "drive_assets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    drive_file_id = Column(String, unique=True, nullable=False, index=True)
    brand_id = Column(String, ForeignKey("brands.id"), nullable=False, index=True)
    product_id = Column(String, ForeignKey("products.id"), nullable=True, index=True)
    format = Column(String, nullable=False)
    folder_path = Column(String, nullable=True)
    file_name = Column(String, nullable=False)
    r2_key = Column(String, nullable=False)
    thumbnail_r2_key = Column(String, nullable=True)
    drive_modified_time = Column(DateTime(timezone=True), nullable=False)
    synced_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    archived = Column(Boolean, default=False, nullable=False)
    soft_tags = Column(String, nullable=True)
    variant = Column(String, nullable=True)
    geo = Column(String, nullable=True)
```

Suggested singleton state table:

```python
class DriveSyncState(Base):
    __tablename__ = "drive_sync_state"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

Migration rules for this repo:
- Use `has_table()` guards for both `op.create_table()` calls.
- Point `down_revision` at the current single Alembic head.
- Run `python3 scripts/check_alembic_heads.py`.

## Runtime Env

Required:
- `GOOGLE_SERVICE_ACCOUNT_JSON` — base64-encoded service account JSON.
- `GOOGLE_DRIVE_ROOT_FOLDER_ID` — current master folder ID: `1SfyeCOcW5HWTjbv5a2scJnoix_U0Ah1e`.

The service account already shared on the folder is `ad-builder-drive-sync@bhm-automations-494217.iam.gserviceaccount.com`.

## Remaining Follow-Up

Drive sync + library UI done — needs migration + `AdCreativeStep.jsx` wiring in Claude Code before this reaches ad launch.
