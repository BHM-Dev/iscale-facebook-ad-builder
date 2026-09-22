import base64
import binascii
import io
import json
import logging
import mimetypes
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.uploads import get_s3_client
from app.core.config import settings
from app.services import slack_service

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
STATE_KEY = "drive_changes_start_page_token"
SUPPORTED_PREFIXES = ("image/", "video/")
TEXT_PREFIXES = ("text/",)
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"


@dataclass
class ResolvedDrivePath:
    brand_folder: str
    folder_path: str


class DriveSyncService:
    """Incrementally sync Google Drive creative files into the existing R2 bucket."""

    def __init__(self, db: Session):
        self.db = db
        self.root_folder_id = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", "")
        self._drive = None
        self._path_cache: Dict[str, Optional[List[Dict[str, str]]]] = {}
        self._folder_metadata_cache: Dict[str, Dict[str, Any]] = {}
        self._package_folder_cache: Dict[str, Optional[str]] = {}
        self._strategy_package_folder_cache: Dict[str, Optional[str]] = {}

    def sync_once(self, backfill: bool = False) -> Dict[str, Any]:
        result = {
            "processed": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "archived": 0,
            "unmatched_brand": 0,
            "errors": 0,
            "unverified": 0,
            "next_page_token_saved": False,
        }

        try:
            self._validate_tables()
            # Keep a manual backfill and the scheduler from racing the same
            # Drive checkpoint or uploading the same newly-seen media twice.
            acquired = self.db.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": "drive_asset_sync"},
            ).scalar()
            if not acquired:
                raise HTTPException(
                    status_code=409,
                    detail="A Drive sync is already running. Wait for it to finish, then refresh copy matches again.",
                )
            drive = self._client()
            page_token = self._get_state_token()

            if backfill or not page_token:
                start_token = self._get_start_page_token(drive)
                files = self._initial_folder_walk(drive)
                for file_meta in files:
                    self._process_file(file_meta, result)
                result["processed"] += len(files)
                # A backfill re-reads current metadata, but it must not advance
                # past change events (especially deletions) that occurred after
                # the existing checkpoint. The next ordinary sync replays them.
                # On a genuinely new installation there is no checkpoint yet,
                # so the walk's start token is safe to save.
                if not page_token:
                    # Replay changes that happened during the walk before
                    # saving the post-walk checkpoint. This closes the race
                    # where a newly added or deleted file would otherwise be
                    # permanently hidden behind the initial token.
                    replay_token = start_token
                    final_token = start_token
                    while replay_token:
                        response = drive.changes().list(
                            pageToken=replay_token,
                            spaces="drive",
                            fields=(
                                "nextPageToken,newStartPageToken,"
                                "changes(removed,fileId,file(id,name,mimeType,parents,modifiedTime,trashed,size,webViewLink))"
                            ),
                            includeItemsFromAllDrives=True,
                            supportsAllDrives=True,
                        ).execute()
                        for change in response.get("changes", []):
                            result["processed"] += 1
                            if change.get("removed"):
                                result["archived"] += self._archive_by_drive_id(change.get("fileId"))
                            elif change.get("file"):
                                self._process_file(change["file"], result)
                        replay_token = response.get("nextPageToken")
                        final_token = response.get("newStartPageToken") or final_token
                    self._set_state_token(final_token)
                    result["next_page_token_saved"] = True
                self.db.commit()
                return result

            next_token = page_token
            while next_token:
                response = drive.changes().list(
                    pageToken=next_token,
                    spaces="drive",
                    fields=(
                        "nextPageToken,newStartPageToken,"
                        "changes(removed,fileId,file(id,name,mimeType,parents,modifiedTime,trashed,size,webViewLink))"
                    ),
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                ).execute()

                for change in response.get("changes", []):
                    result["processed"] += 1
                    if change.get("removed"):
                        result["archived"] += self._archive_by_drive_id(change.get("fileId"))
                        continue
                    file_meta = change.get("file") or {}
                    if file_meta.get("trashed"):
                        result["archived"] += self._archive_by_drive_id(file_meta.get("id"))
                        continue
                    self._process_file(file_meta, result)

                if response.get("newStartPageToken"):
                    self._set_state_token(response["newStartPageToken"])
                    result["next_page_token_saved"] = True
                next_token = response.get("nextPageToken")

            self.db.commit()
            return result
        except Exception as exc:
            self.db.rollback()
            logger.exception("Drive creative sync failed")
            slack_service.send_drive_sync_alert(type(exc).__name__, str(exc))
            raise

    def refresh_copy_metadata(self) -> Dict[str, Any]:
        """Refresh copy tags without reprocessing every Drive media binary.

        A full backfill is intentionally comprehensive, but it is unsuitable for
        repairing a strategy document: it can hold the request open for minutes
        while walking every image. This path lists the tree once, inspects text
        files only, and refreshes packages with supported copy structures.
        """
        result = {
            "processed": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "archived": 0,
            "unmatched_brand": 0,
            "errors": 0,
            "unverified": 0,
            "next_page_token_saved": False,
        }
        try:
            self._validate_tables()
            acquired = self.db.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": "drive_asset_sync"},
            ).scalar()
            if not acquired:
                raise HTTPException(
                    status_code=409,
                    detail="A Drive sync is already running. Wait for it to finish, then refresh copy matches again.",
                )
            drive = self._client()
            # Treat the source tree as authoritative. A document may have been
            # deleted or changed into an unsupported draft since the previous
            # run; it will no longer appear as a recognized document below, so
            # there is no individual file we can safely use to revoke its old
            # match. Mark every existing Drive-derived match unverified first.
            # Each source that still parses successfully overwrites its package
            # with fresh verified tags during this same transaction.
            self._mark_all_copy_assets_unverified(
                "No current recognized Drive copy source was found during refresh"
            )
            for file_meta in self._initial_folder_walk(drive):
                if not self._is_text_file(file_meta.get("mimeType") or "", file_meta.get("name", "")):
                    continue
                result["processed"] += 1
                try:
                    text_body = self._download_text_file(file_meta["id"])
                except Exception as exc:
                    result["errors"] += 1
                    logger.warning("Could not read Drive text file %s during copy refresh: %s", file_meta.get("name"), exc)
                    self._mark_package_copy_unverified(file_meta, str(exc))
                    continue
                is_handoff_manifest = all(token in (file_meta.get("name") or "").lower() for token in ("handoff", "manifest"))
                if not (
                    self._looks_like_strategy_copy_doc(text_body)
                    or self._looks_like_category_copy_doc(text_body)
                    or self._looks_like_ad_copy_doc(text_body)
                    or is_handoff_manifest
                ):
                    continue
                self._package_folder_cache.clear()
                self._strategy_package_folder_cache.clear()
                self._folder_metadata_cache.clear()
                try:
                    result["updated"] += self._refresh_folder_copy_metadata(file_meta)
                except Exception as exc:
                    # Do not roll the whole refresh back and keep last week's
                    # copy silently launchable. Mark only this package's prior
                    # tags unverified; unaffected packages can still refresh,
                    # while this one fails closed in the Creative step until its
                    # source document parses again.
                    result["errors"] += 1
                    logger.warning("Could not refresh Drive copy metadata for %s: %s", file_meta.get("name"), exc)
                    self._mark_package_copy_unverified(file_meta, str(exc))
            result["unverified"] = int(
                self.db.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM drive_assets
                        WHERE archived = FALSE
                          AND COALESCE(NULLIF(soft_tags, '')::jsonb ->> 'copy_refresh_status', '') = 'unverified'
                        """
                    )
                ).scalar()
                or 0
            )
            self.db.commit()
            return result
        except Exception as exc:
            self.db.rollback()
            logger.exception("Drive copy metadata refresh failed")
            raise

    def _client(self):
        if self._drive:
            return self._drive
        if not self.root_folder_id:
            raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not configured")

        raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not raw_json:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured")

        try:
            credentials_info = json.loads(base64.b64decode(raw_json).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON must be base64-encoded service account JSON") from exc

        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=SCOPES,
        )
        self._drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return self._drive

    def _validate_tables(self) -> None:
        missing = []
        for table_name in ("drive_assets", "drive_sync_state"):
            exists = self.db.execute(
                text("SELECT to_regclass(:table_name) IS NOT NULL"),
                {"table_name": table_name},
            ).scalar()
            if not exists:
                missing.append(table_name)
        if missing:
            raise RuntimeError(
                "Drive sync database tables are missing: "
                + ", ".join(missing)
                + ". Apply the Claude Code-owned migration before running sync."
            )

    def _get_state_token(self) -> Optional[str]:
        row = self.db.execute(
            text("SELECT value FROM drive_sync_state WHERE key = :key"),
            {"key": STATE_KEY},
        ).first()
        return row[0] if row else None

    def _set_state_token(self, token_value: str) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO drive_sync_state (key, value, updated_at)
                VALUES (:key, :value, NOW())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
                """
            ),
            {"key": STATE_KEY, "value": token_value},
        )

    def _get_start_page_token(self, drive) -> str:
        response = drive.changes().getStartPageToken(
            supportsAllDrives=True,
        ).execute()
        return response["startPageToken"]

    def _initial_folder_walk(self, drive) -> List[Dict[str, Any]]:
        files: List[Dict[str, Any]] = []
        queue = [self.root_folder_id]
        while queue:
            folder_id = queue.pop(0)
            page_token = None
            while True:
                response = drive.files().list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    spaces="drive",
                    pageToken=page_token,
                    fields="nextPageToken,files(id,name,mimeType,parents,modifiedTime,trashed,size,webViewLink)",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                ).execute()
                for item in response.get("files", []):
                    if item.get("mimeType") == "application/vnd.google-apps.folder":
                        queue.append(item["id"])
                    else:
                        files.append(item)
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
        return files

    def _process_file(self, file_meta: Dict[str, Any], result: Dict[str, Any]) -> None:
        drive_file_id = file_meta.get("id")
        mime_type = file_meta.get("mimeType") or ""
        if not drive_file_id or not self._is_supported_media(mime_type, file_meta.get("name", "")):
            if drive_file_id and self._is_text_file(mime_type, file_meta.get("name", "")):
                # A manifest/copy document can arrive after its media files.
                # Do not let a cached "no package" answer hide the new metadata
                # during this same incremental sync (the page token is committed
                # after the whole batch is processed).
                self._package_folder_cache.clear()
                self._strategy_package_folder_cache.clear()
                self._folder_metadata_cache.clear()
                try:
                    result["updated"] += self._refresh_folder_copy_metadata(file_meta)
                except Exception as exc:
                    # The scheduled incremental sync must fail closed per package
                    # too. A malformed or duplicate AD document cannot leave the
                    # previous copy launchable just because a later file change
                    # causes the outer transaction to roll back.
                    result["errors"] += 1
                    logger.warning("Could not refresh Drive copy metadata for %s: %s", file_meta.get("name"), exc)
                    self._mark_package_copy_unverified(file_meta, str(exc))
            result["skipped"] += 1
            return

        resolved = self._resolve_drive_path(file_meta)
        if not resolved:
            result["skipped"] += 1
            return

        brand_id = self._match_brand_id(resolved.brand_folder)
        if not brand_id:
            logger.warning("Skipping Drive asset with unmatched brand folder: %s", resolved.brand_folder)
            result["unmatched_brand"] += 1
            return

        existing = self.db.execute(
            text(
                """
                SELECT id, drive_modified_time, soft_tags
                FROM drive_assets
                WHERE drive_file_id = :drive_file_id
                """
            ),
            {"drive_file_id": drive_file_id},
        ).mappings().first()
        modified_time = self._parse_drive_time(file_meta.get("modifiedTime"))
        if existing and existing["drive_modified_time"] and existing["drive_modified_time"].replace(tzinfo=timezone.utc) == modified_time:
            # Drive metadata can change without the binary changing (for
            # example, a copy doc or manifest is added after image upload).
            # Refresh tags so existing rows can backfill placement/copy data.
            file_name = file_meta.get("name") or f"{drive_file_id}{mimetypes.guess_extension(mime_type) or ''}"
            soft_tags = self._metadata_for_media_file(file_meta, file_name)
            if soft_tags:
                try:
                    parsed_tags = json.loads(existing["soft_tags"] or "{}")
                    existing_tags = parsed_tags if isinstance(parsed_tags, dict) else {}
                except (TypeError, json.JSONDecodeError):
                    existing_tags = {}
                merged_tags = {**existing_tags, **soft_tags}
                self.db.execute(
                    text("""
                        UPDATE drive_assets
                        SET archived = FALSE, soft_tags = :soft_tags, synced_at = NOW()
                        WHERE id = :id
                    """),
                    {"id": existing["id"], "soft_tags": json.dumps(merged_tags)},
                )
            else:
                # An empty result can mean "no metadata exists", but it can also
                # mean Drive lookup/download failed. Preserve known tags rather
                # than silently turning a previously paired asset into a single.
                self.db.execute(
                    text("UPDATE drive_assets SET archived = FALSE WHERE id = :id"),
                    {"id": existing["id"]},
                )
            result["skipped"] += 1
            return

        content = self._download_file(drive_file_id)
        file_name = file_meta.get("name") or f"{drive_file_id}{mimetypes.guess_extension(mime_type) or ''}"
        r2_key = self._upload_to_r2(content, file_name, mime_type)
        media_format = "video" if mime_type.startswith("video/") else "image"
        soft_tags = self._metadata_for_media_file(file_meta, file_name)

        params = {
            "id": existing["id"] if existing else str(uuid.uuid4()),
            "drive_file_id": drive_file_id,
            "brand_id": brand_id,
            "product_id": None,
            "format": media_format,
            "folder_path": resolved.folder_path,
            "file_name": file_name,
            "r2_key": r2_key,
            "thumbnail_r2_key": None,
            "drive_modified_time": modified_time,
            "soft_tags": json.dumps(soft_tags) if soft_tags else None,
        }
        self.db.execute(
            text(
                """
                INSERT INTO drive_assets (
                    id, drive_file_id, brand_id, product_id, format, folder_path, file_name,
                    r2_key, thumbnail_r2_key, drive_modified_time, synced_at, archived, soft_tags
                )
                VALUES (
                    :id, :drive_file_id, :brand_id, :product_id, :format, :folder_path, :file_name,
                    :r2_key, :thumbnail_r2_key, :drive_modified_time, NOW(), FALSE, :soft_tags
                )
                ON CONFLICT (drive_file_id) DO UPDATE
                SET brand_id = EXCLUDED.brand_id,
                    product_id = EXCLUDED.product_id,
                    format = EXCLUDED.format,
                    folder_path = EXCLUDED.folder_path,
                    file_name = EXCLUDED.file_name,
                    r2_key = EXCLUDED.r2_key,
                    thumbnail_r2_key = EXCLUDED.thumbnail_r2_key,
                    drive_modified_time = EXCLUDED.drive_modified_time,
                    synced_at = NOW(),
                    archived = FALSE,
                    soft_tags = EXCLUDED.soft_tags
                """
            ),
            params,
        )
        if existing:
            result["updated"] += 1
        else:
            result["created"] += 1

    def _download_file(self, drive_file_id: str) -> bytes:
        request = self._client().files().get_media(fileId=drive_file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def _upload_to_r2(self, file_content: bytes, file_name: str, content_type: str) -> str:
        client = get_s3_client()
        if not client:
            raise HTTPException(status_code=500, detail="R2 storage not configured")

        extension = os.path.splitext(file_name)[1].lower()
        key = f"drive-assets/{uuid.uuid4()}{extension}"
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=file_content,
            ContentType=content_type or "application/octet-stream",
        )
        return f"{settings.R2_PUBLIC_URL}/{key}"

    def _archive_by_drive_id(self, drive_file_id: Optional[str]) -> int:
        if not drive_file_id:
            return 0
        # Copy documents are not themselves stored as Drive assets. The source
        # document ID is written onto every media tag it verified, which lets a
        # normal incremental Drive deletion revoke those media rows immediately.
        self._mark_copy_source_unverified(
            drive_file_id,
            "The Drive copy source was deleted or moved",
        )
        result = self.db.execute(
            text(
                """
                UPDATE drive_assets
                SET archived = TRUE, synced_at = NOW()
                WHERE drive_file_id = :drive_file_id AND archived = FALSE
                """
            ),
            {"drive_file_id": drive_file_id},
        )
        return result.rowcount or 0

    def _resolve_drive_path(self, file_meta: Dict[str, Any]) -> Optional[ResolvedDrivePath]:
        chain = self._parent_chain(file_meta)
        if not chain:
            return None
        root_index = next((idx for idx, item in enumerate(chain) if item["id"] == self.root_folder_id), None)
        if root_index is None or root_index + 1 >= len(chain):
            return None
        brand_folder = chain[root_index + 1]["name"]
        folder_names = [item["name"] for item in chain[root_index + 2 :]]
        return ResolvedDrivePath(
            brand_folder=brand_folder,
            folder_path="/".join(folder_names),
        )

    def _parent_chain(self, file_meta: Dict[str, Any]) -> Optional[List[Dict[str, str]]]:
        parents = file_meta.get("parents") or []
        if not parents:
            return None
        folder_chain = self._folder_chain_to_root(parents[0])
        if not folder_chain:
            return None
        return list(reversed(folder_chain))

    def _folder_chain_to_root(self, folder_id: str) -> Optional[List[Dict[str, str]]]:
        if folder_id in self._path_cache:
            return self._path_cache[folder_id]

        drive = self._client()
        current_id = folder_id
        chain: List[Dict[str, str]] = []
        seen = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            try:
                item = drive.files().get(
                    fileId=current_id,
                    fields="id,name,parents",
                    supportsAllDrives=True,
                ).execute()
            except HttpError as exc:
                logger.warning("Could not resolve Drive parent %s: %s", current_id, exc)
                self._path_cache[folder_id] = None
                return None
            chain.append({"id": item["id"], "name": item.get("name", "")})
            if item["id"] == self.root_folder_id:
                self._path_cache[folder_id] = chain
                return chain
            parents = item.get("parents") or []
            current_id = parents[0] if parents else None

        self._path_cache[folder_id] = None
        return None

    def _match_brand_id(self, brand_folder: str) -> Optional[str]:
        rows = self.db.execute(text("SELECT id, name FROM brands")).mappings().all()
        normalized_folder = self._normalize_name(brand_folder)
        best_id = None
        best_score = 0.0
        for row in rows:
            normalized_brand = self._normalize_name(row["name"])
            if normalized_folder == normalized_brand:
                return row["id"]
            score = SequenceMatcher(None, normalized_folder, normalized_brand).ratio()
            if score > best_score:
                best_id = row["id"]
                best_score = score
        return best_id if best_score >= 0.72 else None

    def _is_supported_media(self, mime_type: str, file_name: str) -> bool:
        if mime_type.startswith(SUPPORTED_PREFIXES):
            return True
        guessed, _ = mimetypes.guess_type(file_name)
        return bool(guessed and guessed.startswith(SUPPORTED_PREFIXES))

    def _is_text_file(self, mime_type: str, file_name: str) -> bool:
        if mime_type == GOOGLE_DOC_MIME:
            return True
        if mime_type.startswith(TEXT_PREFIXES):
            return True
        guessed, _ = mimetypes.guess_type(file_name)
        return bool((guessed and guessed.startswith(TEXT_PREFIXES)) or file_name.lower().endswith(".txt"))

    def _find_package_folder(self, file_meta: Dict[str, Any], max_depth: int = 4) -> Optional[str]:
        """Walk up from a file's immediate parent to find its manifest package.

        Verified live 2026-08-20: a media file's own immediate parent is often a
        typed subfolder ("1x1 Images", "9x16 Images") that is a SIBLING of the
        manifest. Some newer packages also put the manifest itself inside an "Ad
        Copy" child folder. The package root is therefore the nearest ancestor whose
        recursive subtree contains both a manifest and media. Returns None if no such
        root is found within max_depth levels.
        """
        drive = self._client()
        parents = file_meta.get("parents") or []
        current = parents[0] if parents else None
        depth = 0
        # Folders visited on the way up whose result isn't known yet — every one of
        # them resolves to the SAME answer (the package folder we eventually find, or
        # None), so we cache all of them together at the end rather than caching each
        # as None as we go — caching "None" prematurely for a folder that turns out to
        # have a manifest one level further up would wrongly stick for every other file
        # in that same folder afterward.
        visited: List[str] = []
        resolved: Optional[str] = None
        while current and depth < max_depth:
            if current in self._package_folder_cache:
                resolved = self._package_folder_cache[current]
                break
            visited.append(current)
            try:
                folder_items = self._list_folder_subtree(current)
            except Exception as exc:
                logger.warning("Could not check Drive folder %s for a handoff manifest: %s", current, exc)
                break
            has_manifest = any(
                "handoff" in (item.get("name") or "").lower() and "manifest" in (item.get("name") or "").lower()
                for item in folder_items
                if item.get("mimeType") != "application/vnd.google-apps.folder"
            )
            has_media = any(
                self._is_supported_media(item.get("mimeType") or "", item.get("name") or "")
                for item in folder_items
            )
            if has_manifest and has_media:
                if self._is_package_container(current):
                    # `current` is the sync root or a brand root: a folder that holds
                    # MANY packages, so any manifest in its subtree belongs to one
                    # specific child package and not to the file we walked up from.
                    # Stop with resolved=None so the caller falls through to the
                    # content-based strategy resolver (or leaves the asset
                    # unverified) instead of adopting a sibling package's copy.
                    break
                resolved = current
                break
            if has_media and depth >= 1:
                # At this point we have checked both the media's placement folder
                # and its likely package root. Do not climb into a brand root and
                # borrow a manifest from an unrelated sibling package.
                break
            try:
                info = drive.files().get(fileId=current, fields="id,parents", supportsAllDrives=True).execute()
            except Exception as exc:
                logger.warning("Could not resolve parent of Drive folder %s: %s", current, exc)
                break
            parent_ids = info.get("parents") or []
            current = parent_ids[0] if parent_ids else None
            depth += 1
        for folder_id in visited:
            self._package_folder_cache[folder_id] = resolved
        return resolved

    def _is_package_container(self, folder_id: str) -> bool:
        """True when folder_id is the sync root or a brand root.

        Those folders hold many packages rather than being one, so a manifest
        found anywhere in their subtree is always some child package's manifest.
        A chain of length 1 is the sync root itself; length 2 is a brand folder
        sitting directly under it. Verified live 2026-09-21: all 8 manifest-bearing
        packages sit at chain length 3 or 4 and no media folder sits directly under
        the sync root, so nothing currently in Drive is wrongly refused.

        An unresolvable chain returns True -- fail CLOSED, matching the rest of this
        file. Returning False would mean "this is a real package, adopt it", which is
        exactly the wrong-copy leak, and Drive being flaky mid-sync is precisely when
        that would fire. An unverified asset is recoverable; a launched ad is not.
        """
        if folder_id == self.root_folder_id:
            return True
        try:
            chain = self._folder_chain_to_root(folder_id)
        except Exception as exc:
            # _folder_chain_to_root only catches HttpError; a timeout or reset would
            # otherwise propagate and kill the whole sync run mid-way.
            logger.warning("Could not resolve Drive folder chain for %s: %s", folder_id, exc)
            return True
        if not chain:
            return True
        return len(chain) <= 2

    @staticmethod
    def _copy_entry_owner_ids(metadata: Dict[str, Any]) -> List[str]:
        """Drive file IDs a copy entry was actually resolved to, if any.

        Both the handoff-manifest and strategy builders record the concrete
        `drive_file_id` they matched a manifest/doc entry to, out of the media
        found in the resolved package's own subtree. `drive_file_ids` (plural)
        is accepted for forward compatibility with a duplicate-basename entry.
        """
        ids = metadata.get("drive_file_ids")
        if not ids:
            single = metadata.get("drive_file_id")
            ids = [single] if single else []
        return [item for item in ids if item]

    def _filename_keyed_metadata(
        self,
        folder_metadata: Dict[str, Any],
        file_name: str,
        drive_file_id: Optional[str],
        package_folder: str,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Look a media file up by lowercased filename, refusing another file's copy.

        Returns (metadata, refusal_tags); at most one is non-empty.

        The by-filename lookup is the ONLY lookup the handoff-manifest path has
        (`_handoff_folder_copy_metadata` returns `assets` keyed by name and no
        `assets_by_drive_id` at all), so it cannot simply be removed. But a
        filename is not unique across packages -- this Drive really does carry the
        same basename in up to six sibling packages (`ad1-identity-9x16.png`) -- so
        whenever `_find_package_folder` resolves too high, the name can hit an
        entry that belongs to a DIFFERENT physical file. That silently attaches a
        sibling package's headline/primary_text/landing_page/CTA to a launchable
        creative, tagged verified, with no integrity flag.

        The builders already resolved each entry to a concrete Drive file ID out of
        the package subtree they were given, so file identity -- not folder shape --
        is the reliable discriminator. Structure cannot work here: a manifest one
        level below the resolved folder is indistinguishable between the legitimate
        `Package/Ad Copy/MANIFEST.txt` layout (live in this Drive) and the
        borrowed `BrandRoot/SiblingPackage/MANIFEST.txt` case.

        An entry with no resolved owner is accepted unchanged: nothing proves it
        belongs to someone else, and rejecting it would unverify assets whose media
        merely has not landed in Drive yet.
        """
        candidate = (folder_metadata.get("assets") or {}).get(file_name.lower())
        if not candidate:
            return {}, {}
        owner_ids = self._copy_entry_owner_ids(candidate)
        if owner_ids and drive_file_id not in owner_ids:
            logger.warning(
                "Refusing copy for Drive file %s (%s): package %s matched it by filename but that "
                "copy entry belongs to Drive file(s) %s. Flagging the asset rather than "
                "attaching another package's copy.",
                drive_file_id,
                file_name,
                package_folder,
                ", ".join(owner_ids),
            )
            return {}, self._copy_refusal_tags(file_name)
        return candidate, {}

    @staticmethod
    def _copy_refusal_tags(file_name: str) -> Dict[str, Any]:
        """Tags that make a refused match visible instead of silently absent.

        Returning {} here would be worse than the bug in one specific way: the
        picker reads `tags.copy_refresh_status || 'verified'`, so an asset with NO
        status key renders as VERIFIED and stays selectable. Worse, only headline
        and primary text would read as missing -- the landing page falls back to
        the brand default and the CTA to the step default, both pre-filled and
        looking correct. A buyer fills the two blanks he is told to fill and
        launches against the wrong URL, losing the package's tracked LP and its
        session passthrough.

        copy_integrity_issue + copy_refresh_status=unverified are the two flags the
        picker already blocks selection on, so this reuses the existing badge and
        block with no frontend change.
        """
        return {
            "copy_integrity_issue": True,
            "copy_refresh_status": "unverified",
            "copy_refresh_error": "copy_matched_another_file",
            # Written for whoever fixes it in Drive, not for a developer reading a log.
            "copy_integrity_reason": (
                f"\"{file_name}\" could not be matched to this package's copy: the copy entry "
                "with that filename resolved to a different image. Give this file a name unique "
                "to its package AND update the copy doc or manifest entry to that new name, then "
                "run Refresh copy from Drive. Renaming the image on its own leaves it with no "
                "copy at all, because the copy entry still points at the old filename."
            ),
            # Deliberately NOT package_folder_id. These tags are merged over an
            # existing row ({**existing, **new}), and package_folder_id is the
            # pairing key in buildDriveAssetGroups. Overwriting it would migrate a
            # refused asset out of its real pair group -- and, on an id collision,
            # into another package's group, blocking that one too. The row's own
            # value is already correct; leave it alone.
            "file_name": file_name,
        }

    def _metadata_for_media_file(self, file_meta: Dict[str, Any], file_name: str) -> Dict[str, Any]:
        drive_file_id = file_meta.get("id")
        # A refusal from the package resolver is held, not returned immediately: the
        # strategy resolver below may still find this file's real copy, and only if
        # it does not should the asset be flagged.
        pending_refusal: Dict[str, Any] = {}
        package_folder = self._find_package_folder(file_meta)
        if package_folder:
            folder_metadata = self._folder_copy_metadata(package_folder)
            # Guarded on a truthy id: a Drive item with no id must not match an
            # entry indexed under a None key.
            metadata = (
                folder_metadata.get("assets_by_drive_id", {}).get(drive_file_id)
                if drive_file_id
                else None
            )
            if not metadata:
                metadata, pending_refusal = self._filename_keyed_metadata(
                    folder_metadata, file_name, drive_file_id, package_folder
                )
            if metadata:
                bound = self._bind_media_metadata_to_file(metadata, drive_file_id)
                if folder_metadata.get("_copy_source_drive_file_id"):
                    bound["copy_source_drive_file_id"] = folder_metadata["_copy_source_drive_file_id"]
                if folder_metadata.get("_copy_source_drive_modified_time"):
                    bound["copy_source_drive_modified_time"] = folder_metadata["_copy_source_drive_modified_time"]
                if folder_metadata.get("_copy_source_drive_file_name"):
                    bound["copy_source_drive_file_name"] = folder_metadata["_copy_source_drive_file_name"]
                return bound
            warning = (folder_metadata.get("_copy_integrity_warnings") or {}).get(drive_file_id)
            if warning:
                return self._bind_media_metadata_to_file(warning, drive_file_id)
        strategy_folder = self._find_strategy_package_folder(file_meta)
        if not strategy_folder:
            return pending_refusal
        folder_metadata = self._folder_copy_metadata(strategy_folder)
        metadata = (
            folder_metadata.get("assets_by_drive_id", {}).get(drive_file_id)
            if drive_file_id
            else None
        )
        if not metadata:
            metadata, strategy_refusal = self._filename_keyed_metadata(
                folder_metadata, file_name, drive_file_id, strategy_folder
            )
            pending_refusal = pending_refusal or strategy_refusal
        bound = self._bind_media_metadata_to_file(metadata, drive_file_id)
        if not bound:
            return pending_refusal
        if folder_metadata.get("_copy_source_drive_file_id"):
            bound["copy_source_drive_file_id"] = folder_metadata["_copy_source_drive_file_id"]
        if folder_metadata.get("_copy_source_drive_modified_time"):
            bound["copy_source_drive_modified_time"] = folder_metadata["_copy_source_drive_modified_time"]
        if folder_metadata.get("_copy_source_drive_file_name"):
            bound["copy_source_drive_file_name"] = folder_metadata["_copy_source_drive_file_name"]
        return bound

    def _bind_media_metadata_to_file(self, metadata: Dict[str, Any], drive_file_id: Optional[str]) -> Dict[str, Any]:
        """Return copy tags without leaking a duplicate basename's sibling ID."""
        if not metadata:
            return {}
        bound = dict(metadata)
        sibling_ids = bound.pop("drive_file_ids", None)
        if sibling_ids:
            bound["drive_file_id"] = drive_file_id
        return bound

    def _write_merged_soft_tags(self, drive_file_id: str, new_tags: Dict[str, Any]) -> int:
        """Merge new_tags into a drive_assets row's existing soft_tags rather than
        overwriting the whole column. A row accumulates tags across multiple sync
        passes (initial match, refresh, copy-integrity warning) — a raw overwrite
        silently drops fields (source, copy_id, copy_source_drive_file_id, ...) that
        an earlier pass set and this one didn't happen to recompute."""
        existing = self.db.execute(
            text("SELECT soft_tags FROM drive_assets WHERE drive_file_id = :drive_file_id"),
            {"drive_file_id": drive_file_id},
        ).mappings().first()
        try:
            parsed = json.loads(existing["soft_tags"]) if existing and existing["soft_tags"] else {}
            existing_tags = parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            existing_tags = {}
        merged_tags = {**existing_tags, **new_tags}
        result = self.db.execute(
            text(
                """
                UPDATE drive_assets
                SET soft_tags = :soft_tags, synced_at = NOW()
                WHERE drive_file_id = :drive_file_id
                """
            ),
            {"soft_tags": json.dumps(merged_tags), "drive_file_id": drive_file_id},
        )
        return result.rowcount or 0

    def _refresh_folder_copy_metadata(self, file_meta: Dict[str, Any]) -> int:
        parents = file_meta.get("parents") or []
        if not parents:
            return 0
        resolved = self._resolve_drive_path(file_meta)
        if not resolved:
            return 0
        brand_id = self._match_brand_id(resolved.brand_folder)
        if not brand_id:
            # Copy documents are resolved to an exact package folder below the
            # configured Drive root.  Unlike media ingestion, refresh does not
            # need a brand row to safely update the existing package assets: the
            # package_folder_id is the binding key used below.  A renamed or
            # newly-created brand folder therefore must not make Joel's current
            # copy invisible after a refresh.  Keep the lookup for diagnostics,
            # but let the package resolver remain authoritative here.
            logger.warning(
                "Refreshing Drive copy for brand folder %s with no matching brand row; using resolved package folder",
                resolved.brand_folder,
            )

        # Only a handoff manifest names its own package by filename, which is the
        # single thing _find_package_folder recognizes. Its "has_media and depth >= 1"
        # guard also assumes the walk started at a media file inside a placement
        # subfolder ("1x1 Images"), one level below the package root. A strategy or
        # category doc sitting directly IN its package root is already at depth 0, so
        # that guard lets the walk climb one level too far and adopt an unrelated
        # sibling package's manifest — refreshing that package instead while this
        # doc's own media is never matched and stays unverified forever. Content
        # matching (_find_strategy_package_folder) resolves those docs correctly, so
        # prefer it for anything that is not a handoff manifest.
        doc_name = (file_meta.get("name") or "").lower()
        is_handoff_manifest = "handoff" in doc_name and "manifest" in doc_name
        # Both branches keep the other resolver as a fallback: a doc whose filename
        # merely happens to contain both tokens ("Creative-Handoff-Manifest-Strategy
        # -Notes.md") is not a manifest to _folder_copy_metadata either, and would
        # otherwise silently resolve to nothing.
        metadata_folder = (
            self._find_package_folder(file_meta) or self._find_strategy_package_folder(file_meta)
            if is_handoff_manifest
            else self._find_strategy_package_folder(file_meta) or self._find_package_folder(file_meta)
        )
        if not metadata_folder:
            return 0
        folder_metadata = self._folder_copy_metadata(metadata_folder, force=True)
        updated = 0
        refresh_assets = folder_metadata.get("assets_by_drive_id") or folder_metadata.get("assets", {})
        matched_media_ids = set()
        for file_name, soft_tags in refresh_assets.items():
            if folder_metadata.get("assets_by_drive_id"):
                file_name = soft_tags.get("file_name") or file_name
            drive_file_ids = soft_tags.get("drive_file_ids") or ([soft_tags.get("drive_file_id")] if soft_tags.get("drive_file_id") else [])
            if not drive_file_ids:
                # A manifest names this file (via its 1x1:/9x16: entry) but no media
                # file with that exact name was found in the same Drive listing pass
                # — name mismatch, case/whitespace drift, or the file genuinely isn't
                # there yet. This is exactly the case most worth knowing about (its
                # copy metadata silently never refreshes), so log it rather than
                # skipping silently.
                logger.warning(
                    "Drive manifest references %s but no matching media file was found to refresh its copy metadata",
                    file_name,
                )
                continue
            for drive_file_id in drive_file_ids:
                matched_media_ids.add(drive_file_id)
                refreshed_tags = self._bind_media_metadata_to_file(soft_tags, drive_file_id)
                refreshed_tags["copy_source_drive_file_id"] = (
                    folder_metadata.get("_copy_source_drive_file_id") or file_meta.get("id")
                )
                refreshed_tags["copy_source_drive_modified_time"] = (
                    folder_metadata.get("_copy_source_drive_modified_time")
                    or file_meta.get("modifiedTime")
                )
                refreshed_tags["copy_source_drive_file_name"] = (
                    folder_metadata.get("_copy_source_drive_file_name")
                    or file_meta.get("name")
                )
                # A successful match is the ONLY thing that clears the blanket
                # "unverified" mark refresh_copy_metadata sets before its walk.
                # _write_merged_soft_tags merges ({**existing, **new}), so without
                # writing the status explicitly here the stale flag survives every
                # re-verification and the fail-closed mark becomes a one-way ratchet:
                # once an asset carries a `source` tag it is marked unverified on
                # every later run and can never recover, however clean its copy doc.
                refreshed_tags["copy_refresh_status"] = "verified"
                refreshed_tags["copy_refresh_error"] = None
                # copy_integrity_issue is written True in exactly one place and
                # never written False, so it ratchets the same way: an image whose
                # filename/heading mismatch was since fixed in Drive stays blocked
                # forever on a flag no refresh can clear, while its badge tells the
                # buyer to "refresh Drive" — the one action that provably cannot
                # help. An item with a live warning `continue`s before reaching this
                # loop, and the warnings loop below re-asserts True within this same
                # run, so clearing it on a fresh match cannot unblock a real problem.
                refreshed_tags["copy_integrity_issue"] = False
                refreshed_tags["copy_integrity_reason"] = None
                updated += self._write_merged_soft_tags(drive_file_id, refreshed_tags)

        for drive_file_id, warning in (folder_metadata.get("_copy_integrity_warnings") or {}).items():
            updated += self._write_merged_soft_tags(drive_file_id, warning)

        if not matched_media_ids:
            raise RuntimeError("Drive copy document did not resolve to any matching media files")
        self._mark_unmatched_package_assets_unverified(metadata_folder, matched_media_ids)
        return updated

    def _mark_unmatched_package_assets_unverified(self, package_folder: str, matched_media_ids: set[str]) -> None:
        """Block previously tagged package assets absent from the current source.

        A partially parseable category document used to refresh the sections it
        still understood and leave deleted/malformed sections with last run's
        valid-looking tags. The current resolved package metadata is the source
        of truth: any formerly tagged media it does not name must be reviewed
        before it can launch again.
        """
        if not matched_media_ids:
            return
        result = self.db.execute(
            text(
                """
                UPDATE drive_assets
                SET soft_tags = jsonb_set(
                    jsonb_set(COALESCE(NULLIF(soft_tags, '')::jsonb, '{}'::jsonb), '{copy_refresh_status}', '"unverified"'::jsonb, true),
                    '{copy_refresh_error}', '"No matching entry in the current Drive copy source"'::jsonb, true
                )::text,
                synced_at = NOW()
                WHERE COALESCE(NULLIF(soft_tags, '')::jsonb ->> 'package_folder_id', '') = :package_folder
                  AND COALESCE(NULLIF(soft_tags, '')::jsonb ->> 'source', '') IN ('category_copy_doc', 'strategy_copy_doc', 'ad_numbered_copy_doc', 'handoff_manifest')
                  AND NOT (drive_file_id = ANY(CAST(:matched_media_ids AS text[])))
                """
            ),
            {"package_folder": package_folder, "matched_media_ids": list(matched_media_ids)},
        )
        if result.rowcount:
            logger.warning(
                "Marked %s Drive asset(s) unverified because they are absent from current package copy metadata %s",
                result.rowcount,
                package_folder,
            )

    def _mark_all_copy_assets_unverified(self, reason: str) -> None:
        """Fail closed when a full source refresh cannot rediscover a package."""
        self.db.execute(
            text(
                """
                UPDATE drive_assets
                SET soft_tags = jsonb_set(
                    jsonb_set(COALESCE(NULLIF(soft_tags, '')::jsonb, '{}'::jsonb), '{copy_refresh_status}', '\"unverified\"'::jsonb, true),
                    '{copy_refresh_error}', to_jsonb(CAST(:reason AS text)), true
                )::text,
                synced_at = NOW()
                WHERE archived = FALSE
                  AND COALESCE(NULLIF(soft_tags, '')::jsonb ->> 'source', '') IN ('category_copy_doc', 'strategy_copy_doc', 'ad_numbered_copy_doc', 'handoff_manifest')
                """
            ),
            {"reason": str(reason)[:500]},
        )

    def _mark_copy_source_unverified(self, source_drive_file_id: str, reason: str) -> None:
        """Revoke media tags attributed to a deleted/moved copy document."""
        result = self.db.execute(
            text(
                """
                UPDATE drive_assets
                SET soft_tags = jsonb_set(
                    jsonb_set(COALESCE(NULLIF(soft_tags, '')::jsonb, '{}'::jsonb), '{copy_refresh_status}', '\"unverified\"'::jsonb, true),
                    '{copy_refresh_error}', to_jsonb(CAST(:reason AS text)), true
                )::text,
                synced_at = NOW()
                WHERE archived = FALSE
                  AND COALESCE(NULLIF(soft_tags, '')::jsonb ->> 'copy_source_drive_file_id', '') = :source_drive_file_id
                """
            ),
            {"source_drive_file_id": source_drive_file_id, "reason": str(reason)[:500]},
        )
        if result.rowcount:
            logger.warning(
                "Marked %s Drive asset(s) unverified because copy source %s was removed",
                result.rowcount,
                source_drive_file_id,
            )

    def _mark_package_copy_unverified(self, file_meta: Dict[str, Any], reason: str) -> None:
        """Fail closed for a package whose current copy source cannot be verified.

        A refresh used to roll back on a malformed or unreadable source file,
        leaving old `soft_tags` indistinguishable from current approved copy.
        The paired-launch UI would then call those rows matched and launch stale
        copy. Preserve the last parsed fields for inspection, but flag the whole
        package so the UI blocks it until a successful refresh replaces the tags.
        """
        package_folder = self._find_package_folder(file_meta) or self._find_strategy_package_folder(file_meta)
        if not package_folder:
            logger.warning("Could not resolve package folder while marking stale Drive copy for %s", file_meta.get("name"))
            return
        safe_reason = str(reason or "Could not verify current Drive copy")[:500]
        result = self.db.execute(
            text(
                """
                UPDATE drive_assets
                SET soft_tags = jsonb_set(
                    jsonb_set(COALESCE(NULLIF(soft_tags, '')::jsonb, '{}'::jsonb), '{copy_refresh_status}', '"unverified"'::jsonb, true),
                    '{copy_refresh_error}', to_jsonb(CAST(:reason AS text)), true
                )::text,
                synced_at = NOW()
                WHERE COALESCE(NULLIF(soft_tags, '')::jsonb ->> 'package_folder_id', '') = :package_folder
                """
            ),
            {"package_folder": package_folder, "reason": safe_reason},
        )
        logger.warning(
            "Marked %s Drive asset(s) unverified after copy refresh failure in package %s",
            result.rowcount or 0,
            package_folder,
        )

    def _list_folder_subtree(self, folder_id: str, max_files: int = 2000) -> List[Dict[str, Any]]:
        """List every non-folder file anywhere under folder_id, recursively.

        Verified live 2026-08-20 that a real handoff package splits its manifest, copy
        file, and media into separate sibling subfolders (e.g. "Horse and Stable | Fresh
        Creative" contains the manifest directly, plus child folders "1x1 Images",
        "9x16 Images", "Ad Copy", "ICP and Strategy") rather than everything sitting
        beside the manifest. A single non-recursive files().list() on the manifest's own
        folder finds neither the referenced media nor the copy file it points to — this
        was a real feature-breaking gap, not a hypothetical one. max_files is a safety
        cap, not expected to ever bind on a real package.
        """
        drive = self._client()
        collected: List[Dict[str, Any]] = []
        queue = [(folder_id, [])]
        seen_folders = {folder_id}
        while queue and len(collected) < max_files:
            current, current_path = queue.pop(0)
            page_token = None
            while True:
                try:
                    response = drive.files().list(
                        q=f"'{current}' in parents and trashed = false",
                        spaces="drive",
                        pageToken=page_token,
                        fields="nextPageToken,files(id,name,mimeType,modifiedTime)",
                        includeItemsFromAllDrives=True,
                        supportsAllDrives=True,
                    ).execute()
                except Exception as exc:
                    raise RuntimeError(
                        f"Could not list Drive folder {current} while resolving package subtree"
                    ) from exc
                for item in response.get("files", []):
                    if item.get("mimeType") == "application/vnd.google-apps.folder":
                        if item["id"] not in seen_folders:
                            seen_folders.add(item["id"])
                            queue.append((item["id"], [*current_path, item.get("name") or ""]))
                    else:
                        # Preserve the immediate folder name for category-copy docs
                        # whose placement is encoded by the folder ("1x1"/"9x16")
                        # rather than repeated in every image filename.
                        item["_parent_folder_name"] = current_path[-1] if current_path else ""
                        item["_parent_folder_path"] = current_path
                        collected.append(item)
                page_token = response.get("nextPageToken")
                if not page_token or len(collected) >= max_files:
                    break
        if queue or len(collected) >= max_files:
            raise RuntimeError(f"Drive package subtree exceeded the safe {max_files}-file inspection limit")
        return collected

    def _find_strategy_package_folder(self, file_meta: Dict[str, Any], max_depth: int = 4) -> Optional[str]:
        """Find the nearest ancestor containing a strategy-copy markdown document.

        Mirrors `_find_package_folder`'s per-folder-id caching — without it,
        this was doing a full recursive subtree listing PLUS downloading and
        content-sniffing every text file at up to 4 ancestor levels, for
        EVERY text file synced, on every 30-minute sync run, forever. That's
        the majority-case path (most of Joel's Drive has no manifest at all,
        confirmed by the docstring elsewhere in this file), so it's not an
        edge case — a real batch of new files landing in one folder meant one
        full 4-level walk PER FILE with zero reuse (code-auditor pre-push
        review, BLOCKING). Caching every visited folder id to the same
        resolved answer (same trick `_find_package_folder` already uses)
        turns that into effectively one walk per folder, not per file.
        """
        drive = self._client()
        parents = file_meta.get("parents") or []
        current = parents[0] if parents else None
        visited: List[str] = []
        resolved: Optional[str] = None
        depth = 0
        while current and depth < max_depth:
            if current in self._strategy_package_folder_cache:
                resolved = self._strategy_package_folder_cache[current]
                break
            visited.append(current)
            try:
                folder_files = self._list_folder_subtree(current)
            except Exception as exc:
                logger.warning("Could not inspect Drive folder %s for strategy copy docs: %s", current, exc)
                break
            found = False
            has_media = any(
                self._is_supported_media(item.get("mimeType") or "", item.get("name") or "")
                for item in folder_files
            )
            for item in folder_files:
                if not self._is_text_file(item.get("mimeType") or "", item.get("name") or ""):
                    continue
                try:
                    text_body = self._download_text_file(item["id"])
                except Exception:
                    continue
                if (
                    has_media
                    and (
                        self._looks_like_strategy_copy_doc(text_body)
                        or self._looks_like_category_copy_doc(text_body)
                        or self._looks_like_ad_copy_doc(text_body)
                    )
                ):
                    if self._is_package_container(current):
                        # Same rule as _find_package_folder: a brand root holds many
                        # packages, so a copy doc anywhere in its subtree belongs to
                        # one specific child package. _strategy_folder_copy_metadata
                        # would otherwise pair THIS file's name against that doc's
                        # blocks and stamp the entry with this file's own Drive ID --
                        # which the identity check in _filename_keyed_metadata cannot
                        # catch, because the entry really does own this file. Stop the
                        # walk with resolved=None instead.
                        found = True
                        break
                    resolved = current
                    found = True
                    break
            if found:
                break
            if has_media and depth >= 1:
                # The first media ancestor is normally the 1x1/9x16 placement
                # folder; its parent is the package root. If that package has
                # media but no recognized copy source, climbing into a brand
                # root could borrow a sibling package's AD 1 copy. Stop here
                # rather than manufacture a valid-looking cross-package pair.
                break
            try:
                info = drive.files().get(fileId=current, fields="id,parents", supportsAllDrives=True).execute()
            except Exception as exc:
                logger.warning("Could not resolve parent of Drive folder %s: %s", current, exc)
                break
            parent_ids = info.get("parents") or []
            current = parent_ids[0] if parent_ids else None
            depth += 1
        for folder_id in visited:
            self._strategy_package_folder_cache[folder_id] = resolved
        return resolved

    def _folder_copy_metadata(self, folder_id: str, force: bool = False) -> Dict[str, Any]:
        if not force and folder_id in self._folder_metadata_cache:
            return self._folder_metadata_cache[folder_id]

        try:
            folder_files = self._list_folder_subtree(folder_id)
        except Exception as exc:
            raise RuntimeError(f"Could not list Drive folder metadata {folder_id}") from exc
        text_files = sorted(
            (
                item for item in folder_files
                if self._is_text_file(item.get("mimeType") or "", item.get("name") or "")
            ),
            key=lambda item: item.get("modifiedTime") or "",
            reverse=True,
        )
        media_by_name = {
            (item.get("name") or "").lower(): item
            for item in folder_files
            if self._is_supported_media(item.get("mimeType") or "", item.get("name") or "")
        }
        manifest = next(
            (item for item in text_files if "handoff" in item.get("name", "").lower() and "manifest" in item.get("name", "").lower()),
            None,
        )
        if manifest:
            try:
                manifest_text = self._download_text_file(manifest["id"])
            except Exception as exc:
                # A refresh must fail closed: returning an empty mapping here
                # would make the caller clear otherwise-valid matched tags.
                raise RuntimeError(f"Could not read Drive handoff manifest {manifest.get('name')}") from exc

            metadata = self._handoff_folder_copy_metadata(folder_id, folder_files, text_files, media_by_name, manifest_text)
            metadata["_copy_source_drive_file_id"] = manifest.get("id")
            metadata["_copy_source_drive_modified_time"] = manifest.get("modifiedTime")
            metadata["_copy_source_drive_file_name"] = manifest.get("name")
            self._folder_metadata_cache[folder_id] = metadata
            return metadata

        copy_candidates = []
        unreadable_text_files = []
        for item in text_files:
            try:
                candidate_text = self._download_text_file(item["id"])
            except Exception:
                unreadable_text_files.append(item.get("name") or item.get("id"))
                continue
            source_kind = self._copy_document_kind(candidate_text)
            if source_kind:
                copy_candidates.append((item, candidate_text, source_kind))
        strategy_file = None
        strategy_text = ""
        strategy_kind = None
        if copy_candidates:
            strategy_file, strategy_text, strategy_kind = max(
                copy_candidates,
                key=lambda candidate: self._copy_document_priority(candidate[0], candidate[2]),
            )
            ignored_candidates = [candidate[0].get("name") for candidate in copy_candidates if candidate[0].get("id") != strategy_file.get("id")]
            if ignored_candidates:
                logger.info(
                    "Selected Drive copy source %s for package %s; ignored lower-priority candidates: %s",
                    strategy_file.get("name"),
                    folder_id,
                    ", ".join(name for name in ignored_candidates if name),
                )
        if strategy_file:
            if strategy_kind == "strategy":
                metadata = self._strategy_folder_copy_metadata(folder_id, folder_files, media_by_name, strategy_text)
            elif strategy_kind == "category":
                category_media = [
                    item for item in folder_files
                    if self._is_supported_media(item.get("mimeType") or "", item.get("name") or "")
                ]
                metadata = self._category_folder_copy_metadata(folder_id, category_media, strategy_text)
            else:
                ad_media = [
                    item for item in folder_files
                    if self._is_supported_media(item.get("mimeType") or "", item.get("name") or "")
                ]
                metadata = self._ad_numbered_folder_copy_metadata(folder_id, ad_media, strategy_text)
            metadata["_copy_source_drive_file_id"] = strategy_file.get("id")
            metadata["_copy_source_drive_modified_time"] = strategy_file.get("modifiedTime")
            metadata["_copy_source_drive_file_name"] = strategy_file.get("name")
            self._folder_metadata_cache[folder_id] = metadata
            return metadata

        if unreadable_text_files:
            # We cannot distinguish a harmless unreadable note from the only
            # strategy document without risking removal of current copy tags.
            raise RuntimeError(
                "Could not verify Drive copy metadata because text file(s) were unreadable: "
                + ", ".join(unreadable_text_files)
            )

        self._folder_metadata_cache[folder_id] = {"assets": {}}
        return self._folder_metadata_cache[folder_id]

    def _copy_document_kind(self, text_body: str) -> Optional[str]:
        """Return the parser kind for a complete, supported copy source."""
        if self._looks_like_strategy_copy_doc(text_body):
            return "strategy"
        if self._looks_like_category_copy_doc(text_body):
            return "category"
        if self._looks_like_ad_copy_doc(text_body):
            return "ad"
        return None

    @staticmethod
    def _copy_document_priority(file_meta: Dict[str, Any], source_kind: str) -> tuple:
        """Rank copy sources deterministically instead of trusting Drive order.

        Packages commonly contain an ICP/reference document and one or more
        alternate/winner variations beside the live copy file. The explicit
        ``Ad Copy``/``Ad-Copy`` name is the canonical source for the package;
        alternate and reference files remain discoverable but must not silently
        replace it when they are newer.
        """
        name = (file_meta.get("name") or "").lower()
        # Tokenize on non-alphanumeric separators so a marker word only counts
        # when it stands alone (e.g. "Winner-Variations-Ad-Copy.txt"), not when
        # it's embedded in an unrelated token (e.g. "AdCopy_Variation2.txt" or
        # "AdCopy_ICPersonas.txt" naming a canonical file's version/persona).
        tokens = set(re.split(r"[^a-z0-9]+", name))
        if tokens & {"winner", "winners", "variation", "variations"}:
            name_priority = 200
        elif re.search(r"(?:ad[\s_-]*copy|copy[\s_-]*ad)", name):
            name_priority = 300
        elif tokens & {"icp", "reference", "references", "strategy"}:
            name_priority = 100
        else:
            name_priority = 150
        kind_priority = {"ad": 30, "category": 20, "strategy": 10}.get(source_kind, 0)
        # Modified time is only a tie-breaker within the same semantic class.
        # This lets Joel edit the canonical file without a newer alternate doc
        # taking precedence, while still selecting the newest duplicate export.
        return (name_priority, kind_priority, file_meta.get("modifiedTime") or "", file_meta.get("id") or "")

    def _handoff_folder_copy_metadata(self, folder_id, folder_files, text_files, media_by_name, manifest_text):

        manifest_data = self._parse_handoff_manifest(manifest_text)
        entries = manifest_data.get("entries") or {}
        if not entries:
            raise RuntimeError("Drive handoff manifest contained no copy entries")
        incomplete_entries = [
            copy_id for copy_id, entry in entries.items()
            if not entry.get("1x1") or not entry.get("9x16") or not entry.get("copy_file")
        ]
        if incomplete_entries:
            raise RuntimeError(
                "Drive handoff manifest has incomplete entries: "
                + ", ".join(sorted(incomplete_entries))
            )
        copy_file_names = {entry.get("copy_file", "").lower() for entry in manifest_data.get("entries", {}).values() if entry.get("copy_file")}
        copy_files = [
            item for item in text_files
            if item.get("name", "").lower() in copy_file_names
        ]
        available_copy_names = {item.get("name", "").lower() for item in copy_files}
        missing_copy_files = copy_file_names - available_copy_names
        if missing_copy_files:
            raise RuntimeError(
                "Handoff manifest references missing copy file(s): "
                + ", ".join(sorted(missing_copy_files))
            )
        copy_blocks: Dict[str, Dict[str, str]] = {}
        for copy_file in copy_files:
            try:
                copy_blocks.update(self._parse_copy_file(self._download_text_file(copy_file["id"])))
            except Exception as exc:
                # Never overwrite previously valid tags with empty copy data
                # when Drive briefly fails to serve a referenced copy file.
                raise RuntimeError(f"Could not parse Drive copy file {copy_file.get('name')}") from exc

        invalid_copy_blocks = [
            copy_id for copy_id in entries
            if not copy_blocks.get(copy_id.lower(), {}).get("headline", "").strip()
            or not copy_blocks.get(copy_id.lower(), {}).get("primary_text", "").strip()
        ]
        if invalid_copy_blocks:
            raise RuntimeError(
                "Drive copy file has missing headline or primary text for: "
                + ", ".join(sorted(invalid_copy_blocks))
            )

        assets: Dict[str, Dict[str, Any]] = {}
        for copy_id, entry in manifest_data.get("entries", {}).items():
            copy = copy_blocks.get(copy_id.lower(), {})
            for aspect in ("1x1", "9x16"):
                file_name = entry.get(aspect)
                if not file_name:
                    continue
                media_file = media_by_name.get(file_name.lower())
                assets[file_name.lower()] = {
                    "copy_id": copy_id,
                    "aspect": aspect,
                    "copy": copy,
                    "landing_page": manifest_data.get("landing_page"),
                    "cta": manifest_data.get("cta"),
                    "source": "handoff_manifest",
                    "drive_file_id": media_file.get("id") if media_file else None,
                    # Disambiguates copy_id across packages — a recurring batch for
                    # the same brand can plausibly reuse a short prefix like "HST"
                    # and restart numbering at F01 (flagged in review 2026-08-21:
                    # brand_id + copy_id alone isn't guaranteed globally unique).
                    # folder_id here is the resolved PACKAGE folder (via
                    # _find_package_folder), stable across the "1x1 Images"/
                    # "9x16 Images" sibling subfolders since both resolve to the
                    # same package — unlike the per-asset folder_path, which
                    # differs between the two and was the original pairing bug.
                    "package_folder_id": folder_id,
                }

        return {"assets": assets}

    def _looks_like_strategy_copy_doc(self, text_body: str) -> bool:
        return bool(re.search(r"^##\s+AD-[A-Z0-9]+-\d{2}\b", text_body, re.IGNORECASE | re.MULTILINE))

    def _looks_like_category_copy_doc(self, text_body: str) -> bool:
        """Recognize a simple category-indexed copy doc used by mixed batches.

        These docs intentionally do not use the structured `## AD-...` format.
        Joel can name an image with its category and placement (for example
        `restaurant-1x1.png`) and this parser can then join it to the uniquely
        matching numbered section without inspecting image pixels.
        """
        return bool(
            re.search(r"^\s*\d+\.\s+.+$", text_body, re.IGNORECASE | re.MULTILINE)
            and re.search(r"^\s*Headline\s*:", text_body, re.IGNORECASE | re.MULTILINE)
            and re.search(r"^\s*Primary text\s*:", text_body, re.IGNORECASE | re.MULTILINE)
        )

    def _looks_like_ad_copy_doc(self, text_body: str) -> bool:
        """Recognize Joel's package-level AD 1 through AD 5 copy documents.

        These are the established contractor-package format. They use either
        META HEADLINE / PRIMARY TEXT labels or a compact Headline: plus prose
        layout, rather than the category-doc fields above.
        """
        # Drive packages often retain an older ICP/draft markdown file beside
        # the current copy file. Those drafts may contain AD headings and field
        # labels but no complete headline/body pair. Do not classify them as an
        # authoritative source: doing so makes refresh call the AD parser and
        # raise "no complete copy sections" before it reaches the real file.
        normalized_body = re.sub(r"[\ufeff\u200b\u200c\u200d]", "", text_body or "").replace("\u00a0", " ")
        if not re.search(r"^\s*AD\s+\d+\b", normalized_body, re.IGNORECASE | re.MULTILINE):
            return False
        has_headline_label = bool(
            re.search(r"^\s*META\s+HEADLINE\s*:?\s*$", normalized_body, re.IGNORECASE | re.MULTILINE)
            or re.search(r"^\s*Headline\s*:", normalized_body, re.IGNORECASE | re.MULTILINE)
        )
        has_primary_label = bool(
            re.search(r"^\s*PRIMARY\s+TEXT\s*:?\s*$", normalized_body, re.IGNORECASE | re.MULTILINE)
            or re.search(r"^\s*={10,}\s*$", normalized_body, re.MULTILINE)
        )
        return bool(has_headline_label and has_primary_label and self._parse_ad_copy_doc(normalized_body))

    _CATEGORY_ALIASES = {
        1: ("landscaping", "landscaper", "landscapers", "field service", "lawn care", "outdoor crew"),
        2: ("retail", "shop owner", "shop owners", "boutique"),
        3: ("plumbing", "plumbers", "hvac", "home service", "plumber"),
        4: ("restaurant", "restaurants", "food service", "cafe", "cafes", "café"),
        5: ("auto repair", "auto repairs", "auto-repair", "auto shop", "auto-shop", "automotive repair"),
        6: ("contractor", "contractors", "construction", "trade contractor", "trade contractors"),
        7: ("general", "protect what you built", "protect what you ve built", "business owner", "business owners", "broad"),
    }

    # Drive packages created before the naming convention was formalized use
    # short folder/file labels. Keep those abbreviations explicit. A generic
    # one-section copy package may use them when the section heading identifies
    # the same semantic family. Never use a short code from one family as a
    # generic fallback for an unrelated heading.
    _CATEGORY_KEYWORD_ALIASES = (
        (
            ("landscaping", "landscape", "landscaper", "landscapers", "lawn care", "field service", "outdoor crew", "land", "lnd"),
            ("land", "lnd"),
        ),
        (
            ("florist", "florists", "floral", "flower shop", "flower store", "flor", "flr"),
            ("flor", "flr"),
        ),
    )

    def _parse_category_copy_doc(self, text_body: str) -> Dict[int, Dict[str, Any]]:
        headings = list(re.finditer(r"^\s*(\d+)\.\s+(.+?)\s*$", text_body, re.MULTILINE))
        sections: Dict[int, Dict[str, Any]] = {}
        for index, heading in enumerate(headings):
            number = int(heading.group(1))
            block = text_body[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(text_body)]
            headline = re.search(r"^\s*Headline\s*:\s*(.+?)\s*$", block, re.IGNORECASE | re.MULTILINE)
            primary = re.search(
                r"^\s*Primary text\s*:\s*\r?\n?(.*?)(?=^\s*(?:Description|Alt headlines)\s*:|\Z)",
                block,
                re.IGNORECASE | re.MULTILINE | re.DOTALL,
            )
            description = re.search(
                r"^\s*Description\s*:\s*\r?\n?(.*?)(?=^\s*Alt headlines\s*:|\Z)",
                block,
                re.IGNORECASE | re.MULTILINE | re.DOTALL,
            )
            if not headline or not primary:
                continue
            sections[number] = {
                "category": heading.group(2).strip(),
                "headline": self._clean_markdown_value(headline.group(1)),
                "primary_text": self._clean_markdown_value(primary.group(1)),
                "description": self._clean_markdown_value(description.group(1)) if description else None,
            }
        return sections

    def _category_matches(self, file_name: str, category: str, number: int) -> bool:
        normalized_file = self._normalize_name(os.path.splitext(file_name)[0])
        normalized_category = self._normalize_name(category)
        legacy_aliases = self._CATEGORY_ALIASES.get(number, ())
        semantic_aliases = []
        for keywords, keyword_aliases in self._CATEGORY_KEYWORD_ALIASES:
            if any(
                self._name_contains_phrase(normalized_category, self._normalize_name(keyword))
                for keyword in keywords
            ):
                # A known heading uses a semantic group, so `Florist`, `FLR`,
                # and `FLOR` are equivalent. Do not inherit unrelated aliases
                # merely because this section happens to be number 1.
                semantic_aliases.extend((*keywords, *keyword_aliases))

        # Legacy docs can use generic headings and depend on the original
        # numbered fallback. Preserve it when no explicit vertical is present.
        aliases = semantic_aliases or list(legacy_aliases)

        candidates = (normalized_category, *(self._normalize_name(alias) for alias in aliases))
        return any(
            candidate and self._category_candidate_matches_filename(normalized_file, candidate)
            for candidate in candidates
        )

    @staticmethod
    def _name_contains_phrase(normalized_value: str, normalized_phrase: str) -> bool:
        """Match normalized filename tokens without short-code false positives."""
        return f" {normalized_phrase} " in f" {normalized_value} "

    def _category_candidate_matches_filename(self, normalized_file: str, normalized_candidate: str) -> bool:
        """Keep legacy compact-name support while making abbreviations exact tokens."""
        short_aliases = {
            self._normalize_name(alias)
            for _, aliases in self._CATEGORY_KEYWORD_ALIASES
            for alias in aliases
        }
        if normalized_candidate in short_aliases:
            return self._name_contains_phrase(normalized_file, normalized_candidate)
        return normalized_candidate in normalized_file

    def _category_alias_replacements(
        self,
        category: str,
    ) -> Dict[str, str]:
        """Return the short naming aliases that are valid for this copy section."""
        normalized_category = self._normalize_name(category)
        replacements: Dict[str, str] = {}
        for keywords, keyword_aliases in self._CATEGORY_KEYWORD_ALIASES:
            normalized_keywords = tuple(self._normalize_name(keyword) for keyword in keywords)
            category_identifies_vertical = any(
                self._name_contains_phrase(normalized_category, keyword)
                for keyword in normalized_keywords
            )
            if not category_identifies_vertical:
                continue
            canonical = normalized_keywords[0]
            for variant in (*normalized_keywords, *(self._normalize_name(alias) for alias in keyword_aliases)):
                replacements[variant] = canonical
        return replacements

    def _matches_category_short_code(self, file_name: str, category: str) -> bool:
        normalized_file = self._normalize_name(os.path.splitext(file_name)[0])
        aliases = self._category_alias_replacements(category)
        return any(self._name_contains_phrase(normalized_file, alias) for alias in aliases)

    def _category_pair_key(
        self,
        file_name: str,
        category: str = "",
    ) -> str:
        """Stable identity for a category-copy Feed/Stories export.

        Category docs share one copy block across multiple images, so their
        category alone is not enough to join the N square files to N vertical
        files. Strip only the placement token while preserving revision suffixes
        from the filename. We pair a key only when it is unique on both sides;
        duplicate/generic names stay singles rather than being paired by Drive's
        arbitrary listing order.
        """
        stem = os.path.splitext(file_name or "")[0].lower()
        stem = re.sub(r"(?:^|[-_ ])(?:1x1|9x16)(?=$|[-_ ])", " ", stem, flags=re.IGNORECASE)
        normalized_stem = re.sub(r"[-_\s]+", " ", stem).strip()
        for alias, canonical in self._category_alias_replacements(category).items():
            normalized_stem = re.sub(
                rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
                canonical,
                normalized_stem,
            )
        return normalized_stem

    def _parse_ad_copy_doc(self, text_body: str) -> Dict[int, Dict[str, Any]]:
        """Parse package copy where each creative is introduced by an AD number.

        The parser supports the two Drive formats presently in use:
        META HEADLINE / PRIMARY TEXT documents and newer compact Headline:
        documents whose body follows a long equals-rule. A block without both
        headline and body is omitted, so a draft can never produce a misleading
        Copy matched tag.
        """
        # Google Docs/text exports occasionally carry a BOM or zero-width
        # formatting characters from pasted content.  Those characters are
        # invisible to Joel but make an otherwise valid `AD 1` heading fail the
        # anchored parser, which then looks like a document with no complete
        # sections.  Normalize them once at the boundary so refresh and the
        # incremental path use the same tolerant parser.
        text_body = re.sub(r"[\ufeff\u200b\u200c\u200d]", "", text_body or "")
        text_body = text_body.replace("\u00a0", " ")
        headings = list(re.finditer(r"^\s*AD\s+(\d+)\b.*$", text_body, re.IGNORECASE | re.MULTILINE))
        sections: Dict[int, Dict[str, Any]] = {}
        seen_numbers = set()
        landing_match = re.search(r"^\s*Lander\s*:\s*(\S+)", text_body, re.IGNORECASE | re.MULTILINE)
        landing_page = landing_match.group(1).strip() if landing_match else None

        for index, heading in enumerate(headings):
            number = int(heading.group(1))
            if number in seen_numbers:
                # Two unrelated versions of AD 1 in one package are ambiguous;
                # fail closed instead of attaching one version arbitrarily.
                return {}
            seen_numbers.add(number)
            block = text_body[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(text_body)]

            headline_match = re.search(
                r"^\s*META\s+HEADLINE\s*:?\s*\r?\n\s*(.+?)\s*$",
                block,
                re.IGNORECASE | re.MULTILINE,
            ) or re.search(
                r"^\s*Headline\s*:\s*(.+?)\s*$",
                block,
                re.IGNORECASE | re.MULTILINE,
            )
            headline = self._clean_markdown_value(headline_match.group(1)) if headline_match else ""

            description_match = re.search(
                r"^\s*Description\s*:\s*(.+?)\s*$",
                block,
                re.IGNORECASE | re.MULTILINE,
            )
            description = self._clean_markdown_value(description_match.group(1)) if description_match else None

            primary_label = re.search(r"^\s*PRIMARY\s+TEXT\s*:?\s*$", block, re.IGNORECASE | re.MULTILINE)
            if primary_label:
                primary_body = block[primary_label.end():]
                primary_body = re.split(r"^\s*(?:CTA|IMAGE)\s*:", primary_body, maxsplit=1, flags=re.IGNORECASE | re.MULTILINE)[0]
            else:
                dividers = list(re.finditer(r"^\s*={10,}\s*$", block, re.MULTILINE))
                primary_body = block[dividers[0].end():dividers[1].start() if len(dividers) > 1 else len(block)] if dividers else ""
            primary_text = self._clean_markdown_value(primary_body)

            cta_match = re.search(r"^\s*CTA\s*:\s*(.+?)\s*$", block, re.IGNORECASE | re.MULTILINE)
            sections[number] = {
                "headline": headline,
                "primary_text": primary_text,
                "description": description,
                "landing_page": landing_page,
                "cta": self._normalize_cta(cta_match.group(1)) if cta_match else None,
            }
        return {
            number: section
            for number, section in sections.items()
            if section["headline"] and section["primary_text"]
        }

    def _media_aspect(self, item: Dict[str, Any]) -> Optional[str]:
        file_name = item.get("name") or ""
        aspect_match = re.search(r"(?:^|[-_ ])(1x1|9x16)(?:[-_][A-Za-z0-9]+)?(?=\.[^.]+$)", file_name, re.IGNORECASE)
        if aspect_match:
            return aspect_match.group(1).lower()
        for folder_name in reversed(item.get("_parent_folder_path") or [item.get("_parent_folder_name") or ""]):
            folder_aspect = re.match(
                r"^\s*(1x1|9x16)(?:\s+(?:images?|assets?|feed|stories|reels))?\s*$",
                folder_name,
                re.IGNORECASE,
            )
            if folder_aspect:
                return folder_aspect.group(1).lower()
        return None

    def _ad_number_from_file_name(self, file_name: str) -> Optional[int]:
        stem = os.path.splitext(file_name or "")[0]
        match = re.search(r"(?:^|[-_ ])AD\s*0?(\d{1,2})(?=$|[-_ ])", stem, re.IGNORECASE)
        if match:
            return int(match.group(1))
        # The Painting package uses the older CVI-PAINT-01 convention instead
        # of spelling out AD before the number. Keep this fallback restricted
        # to that known family so arbitrary CVI-prefixed files cannot inherit
        # another package's copy. Accept both a suffix and an exact stem.
        cvi_match = re.search(r"^CVI-PAINT-0?(\d{1,2})(?=$|[-_ ])", stem, re.IGNORECASE)
        return int(cvi_match.group(1)) if cvi_match else None

    def _ad_numbered_folder_copy_metadata(self, folder_id, media_files, text_body):
        sections = self._parse_ad_copy_doc(text_body)
        if not sections:
            # An incomplete draft can still reach this lower-level resolver
            # through an incremental media sync. It is not a valid source of
            # copy, but it must not crash the whole Drive sync or trigger the
            # Slack "Google Drive creative sync failed" alert.
            logger.warning(
                "Ignoring Drive AD-numbered copy document with no complete copy sections for package %s",
                folder_id,
            )
            return {"assets": {}, "assets_by_drive_id": {}}

        candidates_by_ad: Dict[int, List[Any]] = {}
        for item in media_files:
            file_name = item.get("name") or ""
            ad_number = self._ad_number_from_file_name(file_name)
            aspect = self._media_aspect(item)
            if ad_number not in sections:
                continue
            candidates_by_ad.setdefault(ad_number, []).append((item, file_name, aspect or "unknown"))

        assets: Dict[str, Dict[str, Any]] = {}
        assets_by_drive_id: Dict[str, Dict[str, Any]] = {}
        for ad_number, candidates in candidates_by_ad.items():
            by_aspect: Dict[str, List[Any]] = {"1x1": [], "9x16": [], "unknown": []}
            for candidate in candidates:
                by_aspect[candidate[2]].append(candidate)
            # A stray export with no known placement makes the AD number
            # ambiguous too. Treating the known 1x1/9x16 files as a valid
            # pair while indexing that third file would both conceal the
            # ambiguity and attempt to assign it a missing paired copy ID.
            paired = (
                len(by_aspect["1x1"]) == 1
                and len(by_aspect["9x16"]) == 1
                and not by_aspect["unknown"]
            )
            copy_ids_by_drive_id = {}
            if paired:
                for candidate in (*by_aspect["1x1"], *by_aspect["9x16"]):
                    copy_ids_by_drive_id[candidate[0].get("id")] = f"AD-{ad_number:02d}"
            else:
                for extra_index, candidate in enumerate(sorted(candidates, key=lambda entry: (
                    entry[2], entry[1].lower(), str(entry[0].get("id") or "")
                )), start=1):
                    copy_ids_by_drive_id[candidate[0].get("id")] = f"AD-{ad_number:02d}-EXTRA-{extra_index}"

            section = sections[ad_number]
            pairing_status = "paired" if paired else "ambiguous"
            for item, file_name, aspect in candidates:
                metadata = {
                    "copy_id": copy_ids_by_drive_id[item.get("id")],
                    "category": f"AD {ad_number}",
                    "aspect": aspect,
                    "copy": {
                        "headline": section["headline"],
                        "primary_text": section["primary_text"],
                        "description": section["description"],
                    },
                    "landing_page": section["landing_page"],
                    "cta": section["cta"],
                    "source": "ad_numbered_copy_doc",
                    "copy_pairing_status": pairing_status,
                    "drive_file_id": item.get("id"),
                    "package_folder_id": folder_id,
                    "file_name": file_name,
                }
                if item.get("id"):
                    assets_by_drive_id[item["id"]] = metadata
                assets[file_name.lower()] = metadata
        return {"assets": assets, "assets_by_drive_id": assets_by_drive_id}

    def _category_folder_copy_metadata(self, folder_id, media_files, text_body):
        sections = self._parse_category_copy_doc(text_body)
        if not sections:
            raise RuntimeError("Drive category copy document contained no complete copy sections")
        assets: Dict[str, Dict[str, Any]] = {}
        assets_by_drive_id: Dict[str, Dict[str, Any]] = {}
        copy_integrity_warnings: Dict[str, Dict[str, Any]] = {}
        candidates = []
        for item in media_files:
            file_name = item.get("name") or ""
            aspect_match = re.search(r"(?:^|[-_ ])(1x1|9x16)(?:[-_][A-Za-z0-9]+)?(?=\.[^.]+$)", file_name, re.IGNORECASE)
            if aspect_match:
                aspect = aspect_match.group(1).lower()
            else:
                folder_aspect = next(
                    (
                        re.match(
                            r"^\s*(1x1|9x16)(?:\s+(?:images?|assets?|feed|stories|reels))?\s*$",
                            folder_name,
                            re.IGNORECASE,
                        )
                        for folder_name in reversed(item.get("_parent_folder_path") or [item.get("_parent_folder_name") or ""])
                        if re.match(
                            r"^\s*(1x1|9x16)(?:\s+(?:images?|assets?|feed|stories|reels))?\s*$",
                            folder_name,
                            re.IGNORECASE,
                        )
                    ),
                    None,
                )
                if not folder_aspect:
                    logger.info("Drive image %s has no placement size in filename or parent folder", file_name)
                    continue
                aspect = folder_aspect.group(1).lower()
            if not aspect:
                continue
            matches = [
                number
                for number, section in sections.items()
                if self._category_matches(file_name, section["category"], number)
            ]
            if not matches and len(sections) == 1 and self._matches_category_short_code(
                file_name, next(iter(sections.values()))["category"]
            ):
                # A one-copy package may omit the full category words from its
                # filenames, but only a short code from that section's own
                # semantic family is safe to use as the fallback.
                matches = [next(iter(sections))]
            if len(matches) != 1:
                if len(matches) > 1:
                    logger.warning("Drive image %s matched multiple copy categories: %s", file_name, matches)
                else:
                    logger.info("Drive image %s has no unique category-copy match", file_name)
                if len(sections) == 1 and item.get("id"):
                    section_category = next(iter(sections.values()))["category"]
                    copy_integrity_warnings[item["id"]] = {
                        "copy_integrity_issue": True,
                        # Named for the person fixing it in Drive, not just for a
                        # developer reading a log — points at the actual filename
                        # and the copy doc's own heading text to check/rename against.
                        "copy_integrity_reason": (
                            f"\"{file_name}\" doesn't match this package's copy section "
                            f"(\"{section_category}\"). Rename it to include a word from "
                            f"that heading, or fix the heading in the copy doc."
                        ),
                        "package_folder_id": folder_id,
                        "file_name": file_name,
                    }
                continue
            number = matches[0]
            section = sections[number]
            candidates.append((item, file_name, number, section, aspect))

        candidates_by_category: Dict[int, List[Any]] = {}
        for candidate in candidates:
            candidates_by_category.setdefault(candidate[2], []).append(candidate)
        for number, category_candidates in candidates_by_category.items():
            by_identity: Dict[str, Dict[str, List[Any]]] = {}
            for candidate in category_candidates:
                identity = self._category_pair_key(
                    candidate[1],
                    category_candidates[0][3]["category"],
                )
                by_identity.setdefault(identity, {"1x1": [], "9x16": []})[candidate[4]].append(candidate)

            # Only a one-to-one filename identity is a trustworthy pair. A
            # listing-order zip can make feed A + story B look fully matched
            # because both legitimately share category copy, while serving the
            # wrong visual in Stories. Ambiguous duplicates intentionally become
            # separate entries for an explicit human review instead.
            pair_keys = sorted(
                key for key, placements in by_identity.items()
                if key and len(placements["1x1"]) == 1 and len(placements["9x16"]) == 1
            )
            copy_ids_by_drive_id: Dict[str, str] = {}
            for pair_index, key in enumerate(pair_keys, start=1):
                copy_id = f"CATEGORY-{number:02d}" if pair_index == 1 else f"CATEGORY-{number:02d}-PAIR-{pair_index}"
                for candidate in (*by_identity[key]["1x1"], *by_identity[key]["9x16"]):
                    copy_ids_by_drive_id[candidate[0].get("id")] = copy_id

            unpaired = [
                candidate for candidate in category_candidates
                if candidate[0].get("id") not in copy_ids_by_drive_id
            ]
            for extra_index, candidate in enumerate(sorted(unpaired, key=lambda entry: (
                self._category_pair_key(
                    entry[1],
                    entry[3]["category"],
                ),
                entry[1].lower(),
                str(entry[0].get("id") or ""),
            )), start=1):
                copy_ids_by_drive_id[candidate[0].get("id")] = f"CATEGORY-{number:02d}-EXTRA-{extra_index}"

            for item, file_name, _, section, aspect in category_candidates:
                copy_id = copy_ids_by_drive_id[item.get("id")]
                metadata = {
                    "copy_id": copy_id,
                    "category": section["category"],
                    "aspect": aspect,
                    "copy": {
                        "headline": section["headline"],
                        "primary_text": section["primary_text"],
                        "description": section.get("description"),
                    },
                    "source": "category_copy_doc",
                    "drive_file_id": item.get("id"),
                    "package_folder_id": folder_id,
                    "file_name": file_name,
                }
                if item.get("id"):
                    assets_by_drive_id[item["id"]] = metadata
            # Keep a basename fallback for older callers, but use the exact Drive
            # ID index whenever available so duplicate names remain distinct.
                assets[file_name.lower()] = metadata
        return {
            "assets": assets,
            "assets_by_drive_id": assets_by_drive_id,
            "_copy_integrity_warnings": copy_integrity_warnings,
        }

    def _strategy_folder_copy_metadata(self, folder_id, folder_files, media_by_name, text_body):
        blocks = self._parse_strategy_copy_doc(text_body)
        # Refresh the valid AD blocks independently. One unfinished block should
        # not prevent Joel's completed ads in the same strategy document from
        # receiving their updated copy. Any media belonging to an incomplete
        # block is deliberately left out of the refreshed mapping; the caller's
        # unmatched-asset pass then marks its previous match unverified.
        complete_blocks = {
            copy_id: block
            for copy_id, block in blocks.items()
            if block.get("headline", "").strip() and block.get("primary_text", "").strip()
        }
        if not complete_blocks:
            raise RuntimeError(
                "Drive strategy document has missing headline or primary text"
            )
        assets: Dict[str, Dict[str, Any]] = {}
        for item in media_by_name.values():
            file_name = item.get("name") or ""
            # Tolerates a trailing revision token between the aspect and the
            # extension (e.g. "...-1x1-v2.png", "...-1x1-final.png") — a real
            # re-export naming pattern that the original lookahead (requiring
            # the extension immediately after 1x1/9x16) silently missed,
            # which meant that file got no soft_tags at all and quietly never
            # merged/autofilled with no error anywhere (code-auditor pre-push
            # review, MEDIUM).
            aspect_match = re.search(r"(?:^|[-_ ])(1x1|9x16)(?:[-_][A-Za-z0-9]+)?(?=\.[^.]+$)", file_name, re.IGNORECASE)
            if not aspect_match:
                continue
            code_match = re.match(r"^(AD-[A-Z0-9]+-\d{2})-", file_name, re.IGNORECASE)
            prefix = code_match.group(1).upper() if code_match else ""
            block = complete_blocks.get(prefix)
            if not block:
                continue
            aspect = aspect_match.group(1).lower()
            assets[file_name.lower()] = {
                "copy_id": prefix,
                "aspect": aspect,
                "copy": {
                    "headline": block.get("headline", ""),
                    "primary_text": block.get("primary_text", ""),
                    "description": None,
                },
                "landing_page": block.get("landing_page"),
                "cta": block.get("cta"),
                "source": "strategy_copy_doc",
                "drive_file_id": item.get("id"),
                "package_folder_id": folder_id,
            }
        return {"assets": assets}

    def _parse_strategy_copy_doc(self, text_body: str) -> Dict[str, Dict[str, Any]]:
        # Verified against a real doc (Auto-Dealership-Two-Ad-Set-Winner-Expansion-
        # Strategy-and-Copy-v2.md): the button label and destination URL live on ONE
        # line — "**CTA:** **Get Quote** to `https://.../quote-v2`." — not on two
        # separate "CTA:"/"Landing page:" lines. Try that combined shape first; a
        # naive single-line CTA-only regex previously matched the WHOLE line
        # including " to `url`." into the button label, producing a garbage CTA
        # enum like "GET_QUOTE_TO_HTTPS_WWW_GETBUSINESSCOVERAGE_COM_QUOTE_V2" and
        # never extracting a landing page at all — confirmed live by running this
        # parser against the real file content before this fix.
        # Note the closing "**" for the label sits AFTER the colon in the real
        # doc ("**CTA:**", not "**CTA**:") — \*{0,2} on both sides of the colon
        # handles that ordering; an earlier version of this regex assumed the
        # closing ** came before the colon and silently never matched, leaving
        # the old whole-line fallback below to swallow the URL into the CTA.
        combined_cta = re.search(
            r"^\s*\*{0,2}(?:CTA|Call to action|Meta button)\*{0,2}\s*:\s*\*{0,2}\s*\*{0,2}([^*`\n]+?)\*{0,2}\s+to\s+`([^`]+)`",
            text_body,
            re.IGNORECASE | re.MULTILINE,
        )
        if combined_cta:
            cta = self._normalize_cta(combined_cta.group(1).strip())
            landing_page = combined_cta.group(2).strip()
        else:
            # Fallback: separate "CTA:" / "Landing page:" lines, in case a future
            # doc splits them instead of combining them on one line.
            shared_cta = re.search(r"^\s*(?:\*\*)?(?:CTA|Call to action|Meta button)(?:\*\*)?\s*:\s*(.+?)\s*$", text_body, re.IGNORECASE | re.MULTILINE)
            landing = re.search(r"^\s*(?:\*\*)?(?:Landing page|Landing URL|Destination URL)(?:\*\*)?\s*:\s*(\S+)\s*$", text_body, re.IGNORECASE | re.MULTILINE)
            cta = self._normalize_cta(self._clean_markdown_value(shared_cta.group(1))) if shared_cta else None
            landing_page = self._clean_markdown_value(landing.group(1)) if landing else None
        headings = list(re.finditer(r"^##\s+(AD-[A-Z0-9]+-\d{2})\b.*$", text_body, re.IGNORECASE | re.MULTILINE))
        blocks: Dict[str, Dict[str, Any]] = {}
        for index, heading in enumerate(headings):
            block_text = text_body[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(text_body)]
            code = heading.group(1).upper()
            blocks[code] = {
                "headline": self._clean_markdown_value(self._extract_strategy_field(block_text, "Meta headline")),
                "primary_text": self._clean_markdown_value(self._extract_strategy_field(block_text, "Primary text")),
                "landing_page": landing_page,
                "cta": cta,
            }
        return blocks

    def _extract_strategy_field(self, block: str, label: str) -> str:
        # Confirmed live against the real production doc (ran the actual parser
        # against Joel's real Drive folder, not synthetic test text): every ad
        # block ends with a "---" horizontal rule before the next `## AD-XX`
        # heading, and the LAST ad in an ad-set is followed by that rule PLUS
        # the next ad-set's own "# Ad Set N — Title" / "**Ad set name:**" /
        # "**Angle:**" header text before its first `## AD-XX` sub-heading. The
        # original lookahead only stopped at another "**Label:**" field or
        # end-of-block, so it silently swallowed the "---" rule and, for the
        # last ad in each set, the ENTIRE next section's header text into
        # whatever field happened to be extracted last (Meta headline, since
        # it's the final field per ad) — for the very last ad in the whole
        # document, this ballooned to include internal production notes,
        # approval-request text, and citation URLs with no next field to stop
        # at. Now also stops at a markdown horizontal rule (---, ***, ___) or
        # any heading line (#, ##, ...), not just another bolded field.
        match = re.search(
            rf"^\s*\*\*{re.escape(label)}:\*\*\s*(.*?)(?=^\s*\*\*[A-Za-z][^\n:]*:\*\*|^\s*(?:-{{3,}}|\*{{3,}}|_{{3,}})\s*$|^\s*#{{1,6}}\s|\Z)",
            block,
            re.IGNORECASE | re.MULTILINE | re.DOTALL,
        )
        return match.group(1).strip() if match else ""

    def _clean_markdown_value(self, value: Optional[str]) -> str:
        return re.sub(r"\*\*|`", "", (value or "")).strip()

    def _download_text_file(self, drive_file_id: str) -> str:
        drive = self._client()
        info = drive.files().get(
            fileId=drive_file_id,
            fields="mimeType",
            supportsAllDrives=True,
        ).execute()
        if info.get("mimeType") == GOOGLE_DOC_MIME:
            request = drive.files().export_media(fileId=drive_file_id, mimeType="text/plain")
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buffer.getvalue().decode("utf-8", errors="replace")
        return self._download_file(drive_file_id).decode("utf-8", errors="replace")

    def _parse_handoff_manifest(self, text_body: str) -> Dict[str, Any]:
        lines = text_body.splitlines()
        landing_page = self._extract_manifest_value(lines, r"Landing page")
        cta_value = self._extract_manifest_value(lines, r"Meta button")
        entries: Dict[str, Dict[str, str]] = {}
        current_id: Optional[str] = None
        active_copy_file: Optional[str] = None
        pending_field: Optional[str] = None

        for index, raw_line in enumerate(lines):
            line = raw_line.strip()
            if not line:
                continue

            copy_file = self._extract_manifest_file_name(line)
            if copy_file:
                active_copy_file = copy_file

            copy_id = self._extract_handoff_copy_id(
                line,
                allow_embedded=bool(re.match(r"^\s*Copy\s*:", line, re.IGNORECASE)),
                following_lines=lines[index + 1:],
            )
            if copy_id:
                current_id = copy_id
                entries.setdefault(current_id, {})
                if active_copy_file:
                    entries[current_id]["copy_file"] = active_copy_file

            if not current_id:
                continue

            if pending_field:
                value = self._manifest_field_value(pending_field, line)
                if value:
                    entries[current_id][pending_field] = value
                pending_field = None

            field_match = re.match(r"^(1x1|9x16|Copy file|Copy)\s*(?::\s*(.*))?$", line, re.IGNORECASE)
            if field_match:
                key = field_match.group(1).lower()
                if key in {"copy", "copy file"}:
                    key = "copy_file"
                value = (field_match.group(2) or "").strip()
                if value:
                    parsed_value = self._manifest_field_value(key, value)
                    if parsed_value:
                        entries[current_id][key] = parsed_value
                else:
                    pending_field = key

            if copy_file:
                entries[current_id]["copy_file"] = copy_file

        return {
            "landing_page": landing_page.rstrip(".,") if landing_page else None,
            "cta": self._normalize_cta(cta_value.rstrip(".,")) if cta_value else None,
            "entries": entries,
        }

    def _parse_copy_file(self, text_body: str) -> Dict[str, Dict[str, str]]:
        blocks: Dict[str, Dict[str, str]] = {}
        lines = text_body.splitlines()
        headings = [
            (index, copy_id)
            for index, line in enumerate(lines)
            if (copy_id := self._extract_handoff_copy_id(
                line,
                following_lines=lines[index + 1:],
            ))
        ]
        for heading_index, (line_index, copy_id) in enumerate(headings):
            next_line = headings[heading_index + 1][0] if heading_index + 1 < len(headings) else len(lines)
            block = "\n".join(lines[line_index + 1:next_line])
            blocks[copy_id.lower()] = {
                "primary_text": self._extract_copy_field(block, "PRIMARY TEXT"),
                "headline": self._extract_copy_field(block, "HEADLINE"),
                "description": self._extract_copy_field(block, "DESCRIPTION"),
            }
        return blocks

    _HANDOFF_COPY_ID = re.compile(
        r"(?P<prefix>[A-Z]{2,6}(?:[ _-]+[A-Z]{1,6}){0,2})[ _-]*(?P<number>\d{1,3})",
        re.IGNORECASE,
    )
    _HANDOFF_NON_ID_LABEL = re.compile(
        r"(?:(?:BATCH|PHASE)\s+\d{1,3}|V\d{1,3}|SCALE|RETARGET)"
        r"(?:\s*(?:[|:\-–—_]\s*.*))?",
        re.IGNORECASE,
    )
    _MANIFEST_FILE_NAME = re.compile(r"([A-Z0-9][A-Z0-9_.-]*\.txt)\b", re.IGNORECASE)

    def _extract_handoff_copy_id(
        self,
        raw_line: str,
        allow_embedded: bool = False,
        following_lines: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Extract one canonical handoff ID from a structurally plausible line."""
        line = self._clean_markdown_value(raw_line).strip()
        if not line or "://" in line:
            return None
        if self._HANDOFF_NON_ID_LABEL.fullmatch(line):
            return None
        if not allow_embedded and re.search(r"\.(?:txt|png|jpe?g|webp|gif|mp4)\b", line, re.IGNORECASE):
            return None

        explicit_match = re.match(r"^(?:Copy|Ad)\s+ID\s*:\s*(.+)$", line, re.IGNORECASE)
        target = explicit_match.group(1) if explicit_match else line
        embedded = allow_embedded or bool(explicit_match)
        match = self._HANDOFF_COPY_ID.search(target) if embedded else self._HANDOFF_COPY_ID.match(target)
        if not match:
            return None

        if not embedded:
            remainder = target[match.end():]
            if remainder and not re.match(r"^\s*(?:[|:\-\u2013\u2014]|_)", remainder):
                return None
            # A real copy heading can have a short human-readable concept line
            # before its first field label (for example, ``AD DEALER CR 00`` /
            # ``CONTROL RECREATION`` / ``PRIMARY TEXT``). Looking only at the
            # immediate next line incorrectly rejected every such Auto Dealer
            # package. Keep the lookahead deliberately bounded: the separate
            # Batch/Phase/Vn guard above still rejects known incidental labels.
            if (
                not remainder
                and following_lines is not None
                and not self._has_handoff_structure_ahead(following_lines)
            ):
                return None

        tokens = [token.upper() for token in re.split(r"[ _-]+", match.group("prefix")) if token]
        number = match.group("number")
        if tokens and len(tokens[-1]) == 1:
            tokens[-1] = f"{tokens[-1]}{number}"
        else:
            tokens.append(number)
        return " ".join(tokens)

    def _looks_like_handoff_structure(self, raw_line: str) -> bool:
        line = self._clean_markdown_value(raw_line).strip()
        if not line:
            return False
        if re.match(
            rf"^(?:PRIMARY TEXT|HEADLINE|DESCRIPTION|Copy(?: ID| file| concept)?|\d+[Xx]\d+(?:\s+(?:VISUAL\s+)?(?:SCENE|IMAGE))?)\s*(?::|$)",
            line,
            re.IGNORECASE,
        ):
            return True
        return bool(self._extract_handoff_copy_id(line))

    def _has_handoff_structure_ahead(
        self,
        raw_lines: List[str],
        max_plain_lines: int = 2,
    ) -> bool:
        """Confirm a bare handoff ID has nearby copy/manifest structure.

        Live handoff files use at most one intervening concept line between an
        ID and its first field label. Two lines leaves room for a future title
        plus subtitle, but never scans through an unbounded copy body.
        """
        plain_lines = 0
        for raw_line in raw_lines:
            line = self._clean_markdown_value(raw_line).strip()
            if not line:
                continue
            if self._looks_like_handoff_structure(line):
                return True
            plain_lines += 1
            if plain_lines > max_plain_lines:
                return False
        return False

    def _extract_manifest_value(self, lines: List[str], label: str) -> Optional[str]:
        for index, raw_line in enumerate(lines):
            line = raw_line.strip()
            match = re.match(rf"^(?:-\s*)?{label}\s*(?::\s*(.*))?$", line, re.IGNORECASE)
            if not match:
                continue
            inline_value = (match.group(1) or "").strip()
            if inline_value:
                return inline_value
            for following in lines[index + 1:]:
                value = following.strip()
                if value:
                    return value
        return None

    def _extract_manifest_file_name(self, line: str) -> Optional[str]:
        matches = self._MANIFEST_FILE_NAME.findall(line)
        return os.path.basename(matches[-1].replace("\\", "/")) if matches else None

    def _manifest_field_value(self, key: str, value: str) -> Optional[str]:
        if key == "copy_file":
            return self._extract_manifest_file_name(value)
        return os.path.basename(value.replace("\\", "/")).strip() or None

    # Known section labels a copy-file block can be followed by. Deliberately an
    # enumerated/narrow pattern, NOT "any all-caps line" — verified live that real ad
    # copy routinely contains standalone all-caps punch lines (e.g. "LIMITED TIME
    # OFFER") inside PRIMARY TEXT/HEADLINE bodies, which a generic all-caps stop-list
    # would misread as a new section and silently truncate the real copy. \d+[Xx]\d+
    # VISUAL SCENE covers the 1X1/9X16 headers confirmed live plus other aspect
    # ratios (4X5, 16X9, etc.) that may appear in other packages without needing to
    # widen this to match arbitrary text.
    _COPY_FIELD_STOP_LABELS = r"PRIMARY TEXT|HEADLINE|DESCRIPTION|\d+[Xx]\d+\s+(?:VISUAL\s+)?(?:SCENE|IMAGE)"

    def _extract_copy_field(self, block: str, label: str) -> str:
        match = re.search(
            rf"^[ \t]*(?i:{re.escape(label)})[ \t]*:?[ \t]*(?:\r?\n)?(.*?)(?=^[ \t]*(?:{self._COPY_FIELD_STOP_LABELS})[ \t]*:?[ \t]*$|^[ \t]*={{4,}}[ \t]*$|\Z)",
            block,
            re.IGNORECASE | re.MULTILINE | re.DOTALL,
        )
        return match.group(1).strip() if match else ""

    # Meta's `call_to_action_types` enum has no server-side free-text fallback —
    # an unrecognized value 400s the entire ad creation call. Naive
    # uppercase-and-underscore normalization only coincidentally produces a
    # valid enum for CTAs that already happen to be shaped like one ("Shop
    # Now" -> SHOP_NOW). A human-written strategy doc is far more likely to
    # phrase it loosely ("Get a Quote", "Get Your Free Quote") than the more
    # controlled manifest format this function was originally built for
    # (code-auditor pre-push review, HIGH — this fix also improves the
    # pre-existing manifest path, not just the new strategy-doc one, since
    # both funnel through here). Mirrors the CTA_OPTIONS whitelist in
    # AdCreativeStep.jsx — keep the two in sync if either changes.
    _CTA_PHRASE_MAP = {
        'LEARN_MORE': 'LEARN_MORE', 'LEARN': 'LEARN_MORE',
        'SHOP_NOW': 'SHOP_NOW', 'SHOP': 'SHOP_NOW',
        'SIGN_UP': 'SIGN_UP',
        'CONTACT_US': 'CONTACT_US', 'CONTACT': 'CONTACT_US',
        'DOWNLOAD': 'DOWNLOAD',
        'BOOK_NOW': 'BOOK_NOW', 'BOOK': 'BOOK_NOW',
        'BUY_TICKETS': 'BUY_TICKETS',
        'GET_STARTED': 'GET_STARTED', 'START': 'GET_STARTED',
        'APPLY_NOW': 'APPLY_NOW', 'APPLY': 'APPLY_NOW',
        'DONATE_NOW': 'DONATE_NOW', 'DONATE': 'DONATE_NOW',
        # GET_QUOTE candidates — every phrasing here collapses to the one
        # valid enum value rather than producing e.g. GET_A_QUOTE, GET_MY_
        # QUOTE, or GET_YOUR_FREE_QUOTE, all of which would 400 at Meta.
        'GET_QUOTE': 'GET_QUOTE', 'GET_A_QUOTE': 'GET_QUOTE',
        'GET_MY_QUOTE': 'GET_QUOTE', 'GET_YOUR_QUOTE': 'GET_QUOTE',
        'GET_YOUR_FREE_QUOTE': 'GET_QUOTE', 'GET_FREE_QUOTE': 'GET_QUOTE',
        'REQUEST_QUOTE': 'GET_QUOTE', 'REQUEST_A_QUOTE': 'GET_QUOTE',
        'GET_RATE_NOW': 'GET_QUOTE', 'GET_MY_RATE_NOW': 'GET_QUOTE',
    }

    def _normalize_cta(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        normalized = re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")
        if not normalized:
            return None
        mapped = self._CTA_PHRASE_MAP.get(normalized)
        if mapped:
            return mapped
        # No known mapping — fall back to the naive normalization (unchanged
        # prior behavior) but log so an unrecognized real-world phrasing
        # surfaces during sync instead of only failing silently at launch
        # time inside a Meta 400 several steps later.
        logger.warning(
            "CTA phrase %r normalized to %r, which isn't a known Meta CTA enum value — "
            "ad creation will likely 400 unless Joel overrides the CTA field manually.",
            value, normalized,
        )
        return normalized

    def _parse_drive_time(self, value: Optional[str]) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _normalize_name(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
