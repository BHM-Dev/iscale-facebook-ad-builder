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

    def sync_once(self) -> Dict[str, Any]:
        result = {
            "processed": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "archived": 0,
            "unmatched_brand": 0,
            "errors": 0,
            "next_page_token_saved": False,
        }

        try:
            self._validate_tables()
            drive = self._client()
            page_token = self._get_state_token()

            if not page_token:
                files = self._initial_folder_walk(drive)
                start_token = self._get_start_page_token(drive)
                for file_meta in files:
                    self._process_file(file_meta, result)
                self._set_state_token(start_token)
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
                result["updated"] += self._refresh_folder_copy_metadata(file_meta)
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
                SELECT id, drive_modified_time
                FROM drive_assets
                WHERE drive_file_id = :drive_file_id
                """
            ),
            {"drive_file_id": drive_file_id},
        ).mappings().first()
        modified_time = self._parse_drive_time(file_meta.get("modifiedTime"))
        if existing and existing["drive_modified_time"] and existing["drive_modified_time"].replace(tzinfo=timezone.utc) == modified_time:
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
        if mime_type.startswith(TEXT_PREFIXES):
            return True
        guessed, _ = mimetypes.guess_type(file_name)
        return bool((guessed and guessed.startswith(TEXT_PREFIXES)) or file_name.lower().endswith(".txt"))

    def _metadata_for_media_file(self, file_meta: Dict[str, Any], file_name: str) -> Dict[str, Any]:
        parents = file_meta.get("parents") or []
        if not parents:
            return {}
        folder_metadata = self._folder_copy_metadata(parents[0])
        return folder_metadata.get("assets", {}).get(file_name.lower(), {})

    def _refresh_folder_copy_metadata(self, file_meta: Dict[str, Any]) -> int:
        parents = file_meta.get("parents") or []
        if not parents:
            return 0
        resolved = self._resolve_drive_path(file_meta)
        if not resolved:
            return 0
        brand_id = self._match_brand_id(resolved.brand_folder)
        if not brand_id:
            return 0

        folder_metadata = self._folder_copy_metadata(parents[0], force=True)
        updated = 0
        for file_name, soft_tags in folder_metadata.get("assets", {}).items():
            result = self.db.execute(
                text(
                    """
                    UPDATE drive_assets
                    SET soft_tags = :soft_tags, synced_at = NOW()
                    WHERE brand_id = :brand_id
                      AND COALESCE(folder_path, '') = :folder_path
                      AND LOWER(file_name) = :file_name
                    """
                ),
                {
                    "soft_tags": json.dumps(soft_tags),
                    "brand_id": brand_id,
                    "folder_path": resolved.folder_path or "",
                    "file_name": file_name,
                },
            )
            updated += result.rowcount or 0
        return updated

    def _folder_copy_metadata(self, folder_id: str, force: bool = False) -> Dict[str, Any]:
        if not force and folder_id in self._folder_metadata_cache:
            return self._folder_metadata_cache[folder_id]

        drive = self._client()
        response = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            spaces="drive",
            fields="files(id,name,mimeType,modifiedTime)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        text_files = [
            item for item in response.get("files", [])
            if self._is_text_file(item.get("mimeType") or "", item.get("name") or "")
        ]
        manifest = next(
            (item for item in text_files if "handoff" in item.get("name", "").lower() and "manifest" in item.get("name", "").lower()),
            None,
        )
        if not manifest:
            self._folder_metadata_cache[folder_id] = {"assets": {}}
            return self._folder_metadata_cache[folder_id]

        try:
            manifest_text = self._download_text_file(manifest["id"])
        except Exception:
            logger.warning("Could not read Drive handoff manifest %s", manifest.get("name"))
            self._folder_metadata_cache[folder_id] = {"assets": {}}
            return self._folder_metadata_cache[folder_id]

        manifest_data = self._parse_handoff_manifest(manifest_text)
        copy_file_names = {entry.get("copy_file", "").lower() for entry in manifest_data.get("entries", {}).values() if entry.get("copy_file")}
        copy_files = [
            item for item in text_files
            if item.get("name", "").lower() in copy_file_names
            or ("copy" in item.get("name", "").lower() and "manifest" not in item.get("name", "").lower())
        ]
        copy_blocks: Dict[str, Dict[str, str]] = {}
        for copy_file in copy_files:
            try:
                copy_blocks.update(self._parse_copy_file(self._download_text_file(copy_file["id"])))
            except Exception:
                logger.warning("Could not parse Drive copy file %s", copy_file.get("name"))

        assets: Dict[str, Dict[str, Any]] = {}
        for copy_id, entry in manifest_data.get("entries", {}).items():
            copy = copy_blocks.get(copy_id.lower(), {})
            for aspect in ("1x1", "9x16"):
                file_name = entry.get(aspect)
                if not file_name:
                    continue
                assets[file_name.lower()] = {
                    "copy_id": copy_id,
                    "aspect": aspect,
                    "copy": copy,
                    "landing_page": manifest_data.get("landing_page"),
                    "cta": manifest_data.get("cta"),
                    "source": "handoff_manifest",
                }

        self._folder_metadata_cache[folder_id] = {"assets": assets}
        return self._folder_metadata_cache[folder_id]

    def _download_text_file(self, drive_file_id: str) -> str:
        return self._download_file(drive_file_id).decode("utf-8", errors="replace")

    def _parse_handoff_manifest(self, text_body: str) -> Dict[str, Any]:
        landing_match = re.search(r"^\s*Landing page\s*:\s*(\S+)", text_body, re.IGNORECASE | re.MULTILINE)
        cta_match = re.search(r"^\s*Meta button\s*:\s*([A-Z_ ]+)", text_body, re.IGNORECASE | re.MULTILINE)
        entries: Dict[str, Dict[str, str]] = {}
        current_id: Optional[str] = None
        for raw_line in text_body.splitlines():
            line = raw_line.strip()
            copy_id_match = re.match(r"(?:Copy ID\s*:\s*)?([A-Z]{2,5}\s*F\d{2})\b", line, re.IGNORECASE)
            if copy_id_match:
                current_id = re.sub(r"\s+", " ", copy_id_match.group(1).upper())
                entries.setdefault(current_id, {})
            if not current_id:
                continue
            field_match = re.match(r"(1x1|9x16|Copy file)\s*:\s*(.+)", line, re.IGNORECASE)
            if field_match:
                key = field_match.group(1).lower()
                if key == "copy file":
                    key = "copy_file"
                entries[current_id][key] = field_match.group(2).strip()
        return {
            "landing_page": landing_match.group(1).strip() if landing_match else None,
            "cta": self._normalize_cta(cta_match.group(1)) if cta_match else None,
            "entries": entries,
        }

    def _parse_copy_file(self, text_body: str) -> Dict[str, Dict[str, str]]:
        blocks: Dict[str, Dict[str, str]] = {}
        for block in re.split(r"\n={4,}\n", text_body):
            copy_id_match = re.search(r"\b([A-Z]{2,5}\s*F\d{2})\b", block, re.IGNORECASE)
            if not copy_id_match:
                continue
            copy_id = re.sub(r"\s+", " ", copy_id_match.group(1).upper())
            blocks[copy_id.lower()] = {
                "primary_text": self._extract_copy_field(block, "PRIMARY TEXT"),
                "headline": self._extract_copy_field(block, "HEADLINE"),
                "description": self._extract_copy_field(block, "DESCRIPTION"),
            }
        return blocks

    def _extract_copy_field(self, block: str, label: str) -> str:
        match = re.search(
            rf"^\s*{re.escape(label)}\s*:?\s*\n?(.*?)(?=^\s*(?:PRIMARY TEXT|HEADLINE|DESCRIPTION)\s*:?\s*$|\Z)",
            block,
            re.IGNORECASE | re.MULTILINE | re.DOTALL,
        )
        return match.group(1).strip() if match else ""

    def _normalize_cta(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        normalized = re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")
        return normalized or None

    def _parse_drive_time(self, value: Optional[str]) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _normalize_name(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
