import base64
import json

import app.services.drive_sync_service as drive_sync_module
from app.services.drive_sync_service import DRIVE_HTTP_TIMEOUT_SECONDS, DriveSyncService


def test_drive_client_uses_bounded_authorized_transport(monkeypatch):
    service = DriveSyncService.__new__(DriveSyncService)
    service._drive = None
    service.root_folder_id = "root-folder"

    monkeypatch.setenv(
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        base64.b64encode(json.dumps({"type": "service_account"}).encode()).decode(),
    )
    credentials = object()
    captured = {}

    monkeypatch.setattr(
        drive_sync_module.service_account.Credentials,
        "from_service_account_info",
        lambda info, scopes: captured.update(info=info, scopes=scopes) or credentials,
    )

    class FakeHttp:
        def __init__(self, timeout):
            captured["timeout"] = timeout

    monkeypatch.setattr(drive_sync_module.httplib2, "Http", FakeHttp)
    monkeypatch.setattr(
        drive_sync_module,
        "AuthorizedHttp",
        lambda supplied_credentials, http: captured.update(credentials=supplied_credentials, http=http) or "authorized-http",
    )
    monkeypatch.setattr(
        drive_sync_module,
        "build",
        lambda service_name, version, http, cache_discovery: captured.update(
            service_name=service_name,
            version=version,
            build_http=http,
            cache_discovery=cache_discovery,
        ) or "drive-client",
    )

    assert service._client() == "drive-client"
    assert service._client() == "drive-client"
    assert captured["timeout"] == DRIVE_HTTP_TIMEOUT_SECONDS
    assert captured["credentials"] is credentials
    assert captured["build_http"] == "authorized-http"
    assert captured["service_name"] == "drive" and captured["version"] == "v3"
