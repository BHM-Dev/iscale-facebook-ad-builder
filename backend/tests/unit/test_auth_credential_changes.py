"""Credential changes need the current password and end sessions (review N3);
new passwords need 12+ characters."""
import pytest
from fastapi import status

from app.core.security import password_problem


def test_password_problem_rule():
    assert password_problem("short") is not None
    assert password_problem("") is not None
    assert password_problem("x" * 11) is not None
    assert password_problem("x" * 12) is None


def _login(client, password="testpassword"):
    r = client.post("/api/v1/auth/login/json",
                    json={"email": "test@example.com", "password": password})
    assert r.status_code == status.HTTP_200_OK
    return r.json()


def _bearer(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


class TestSelfUpdate:
    def test_password_change_without_current_password_is_refused(self, client, test_user):
        t = _login(client)
        r = client.put("/api/v1/auth/me", headers=_bearer(t),
                       json={"password": "a-brand-new-password"})
        assert r.status_code == status.HTTP_403_FORBIDDEN
        _login(client)  # old password still works

    def test_wrong_current_password_is_refused(self, client, test_user):
        t = _login(client)
        r = client.put("/api/v1/auth/me", headers=_bearer(t),
                       json={"email": "new@example.com", "current_password": "nope"})
        assert r.status_code == status.HTTP_403_FORBIDDEN

    def test_short_new_password_is_refused(self, client, test_user):
        t = _login(client)
        r = client.put("/api/v1/auth/me", headers=_bearer(t),
                       json={"password": "short", "current_password": "testpassword"})
        assert r.status_code == status.HTTP_400_BAD_REQUEST

    def test_password_change_revokes_refresh_tokens(self, client, test_user):
        t = _login(client)
        r = client.put("/api/v1/auth/me", headers=_bearer(t),
                       json={"password": "a-brand-new-password",
                             "current_password": "testpassword"})
        assert r.status_code == status.HTTP_200_OK
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
        assert r.status_code == status.HTTP_401_UNAUTHORIZED
        _login(client, "a-brand-new-password")

    def test_name_only_change_needs_no_password(self, client, test_user):
        t = _login(client)
        r = client.put("/api/v1/auth/me", headers=_bearer(t), json={"name": "Renamed"})
        assert r.status_code == status.HTTP_200_OK
        assert r.json()["name"] == "Renamed"
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
        assert r.status_code == status.HTTP_200_OK


@pytest.fixture(autouse=True)
def _cleanup_other_user(db_session):
    yield
    from app.models import RefreshToken, User
    other = db_session.query(User).filter(User.email == "other@example.com").first()
    if other:
        db_session.query(RefreshToken).filter(RefreshToken.user_id == other.id).delete()
        db_session.delete(other)
        db_session.commit()


class TestAdminUpdate:
    def _other_user(self, db_session):
        from app.core.security import get_password_hash
        from app.models import User
        u = User(email="other@example.com", name="Other",
                 hashed_password=get_password_hash("otherpassword"), is_active=True)
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
        return u

    def _promote(self, db_session, test_user):
        test_user.is_superuser = True
        db_session.commit()

    def test_admin_password_reset_ends_target_sessions(self, client, db_session, test_user):
        self._promote(db_session, test_user)
        other = self._other_user(db_session)
        other_tokens = client.post("/api/v1/auth/login/json",
                                   json={"email": "other@example.com",
                                         "password": "otherpassword"}).json()
        admin = _login(client)
        r = client.put(f"/api/v1/users/{other.id}", headers=_bearer(admin),
                       json={"password": "reset-by-admin-123"})
        assert r.status_code == status.HTTP_200_OK
        r = client.post("/api/v1/auth/refresh",
                        json={"refresh_token": other_tokens["refresh_token"]})
        assert r.status_code == status.HTTP_401_UNAUTHORIZED

    def test_admin_short_password_refused(self, client, db_session, test_user):
        self._promote(db_session, test_user)
        other = self._other_user(db_session)
        admin = _login(client)
        r = client.put(f"/api/v1/users/{other.id}", headers=_bearer(admin),
                       json={"password": "short"})
        assert r.status_code == status.HTTP_400_BAD_REQUEST

    def test_toggle_active_still_works(self, client, db_session, test_user):
        self._promote(db_session, test_user)
        other = self._other_user(db_session)
        admin = _login(client)
        r = client.put(f"/api/v1/users/{other.id}", headers=_bearer(admin),
                       json={"is_active": False})
        assert r.status_code == status.HTTP_200_OK
        assert r.json()["is_active"] is False

    def test_admin_self_password_change_needs_current_password(self, client, db_session, test_user):
        self._promote(db_session, test_user)
        admin = _login(client)
        r = client.put(f"/api/v1/users/{test_user.id}", headers=_bearer(admin),
                       json={"password": "a-brand-new-password"})
        assert r.status_code == status.HTTP_403_FORBIDDEN
        r = client.put(f"/api/v1/users/{test_user.id}", headers=_bearer(admin),
                       json={"password": "a-brand-new-password",
                             "current_password": "testpassword"})
        assert r.status_code == status.HTTP_200_OK
