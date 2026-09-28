"""Acceptance tests for workspace-shared Research boards."""
from uuid import uuid4

from app.models import ResearchBoard, ResearchBoardItem, ResearchTestBacklogItem, SavedSearch, ScrapedAd, Vertical


def create_test_ad(db_session, vertical_name=None):
    search_id = None
    if vertical_name:
        vertical = db_session.query(Vertical).filter(Vertical.name == vertical_name).first()
        if not vertical:
            vertical = Vertical(name=vertical_name, description="Test research vertical")
            db_session.add(vertical)
            db_session.flush()
        search = SavedSearch(query="Board test query", vertical_id=vertical.id, search_type="one_time")
        db_session.add(search)
        db_session.flush()
        search_id = search.id
    ad = ScrapedAd(
        brand_name="Board Test Advertiser",
        headline="Board test headline",
        ad_copy="Board test copy",
        ad_link=f"https://www.facebook.com/ads/library/?id={uuid4()}",
        external_id=f"board-test-{uuid4()}",
        is_saved=True,
        search_id=search_id,
    )
    db_session.add(ad)
    db_session.commit()
    db_session.refresh(ad)
    return ad


class TestResearchBoards:
    def test_board_routes_require_auth(self, client):
        assert client.get("/api/v1/research/boards").status_code == 401
        assert client.post("/api/v1/research/boards", json={"name": "Unauthenticated"}).status_code == 401

    def test_shared_board_crud_and_independent_membership(self, client, auth_headers, db_session):
        ad = create_test_ad(db_session, vertical_name="Commercial Insurance")

        first = client.post(
            "/api/v1/research/boards",
            json={"name": "Offers to Test", "vertical_id": "auto_insurance"},
            headers=auth_headers,
        )
        second = client.post(
            "/api/v1/research/boards",
            json={"name": "Joel Review Queue"},
            headers=auth_headers,
        )
        assert first.status_code == 201
        assert second.status_code == 201
        first_id = first.json()["id"]
        second_id = second.json()["id"]
        assert first.json()["item_count"] == 0

        first_add = client.post(
            f"/api/v1/research/boards/{first_id}/items",
            json={"scraped_ad_id": ad.id},
            headers=auth_headers,
        )
        duplicate_add = client.post(
            f"/api/v1/research/boards/{first_id}/items",
            json={"scraped_ad_id": ad.id},
            headers=auth_headers,
        )
        second_add = client.post(
            f"/api/v1/research/boards/{second_id}/items",
            json={"scraped_ad_id": ad.id},
            headers=auth_headers,
        )
        assert first_add.status_code == duplicate_add.status_code == second_add.status_code == 200
        assert first_add.json()["board_item_id"] == duplicate_add.json()["board_item_id"]
        assert first_add.json()["board_item_id"] != second_add.json()["board_item_id"]

        first_items = client.get(f"/api/v1/research/boards/{first_id}/items", headers=auth_headers)
        second_items = client.get(f"/api/v1/research/boards/{second_id}/items", headers=auth_headers)
        assert [item["id"] for item in first_items.json()] == [ad.id]
        assert [item["id"] for item in second_items.json()] == [ad.id]

        # Removing a join row does not unsave the ad or remove it from another board.
        remove = client.delete(
            f"/api/v1/research/boards/{first_id}/items/{first_add.json()['board_item_id']}",
            headers=auth_headers,
        )
        assert remove.status_code == 200
        assert client.get(f"/api/v1/research/boards/{first_id}/items", headers=auth_headers).json() == []
        assert len(client.get(f"/api/v1/research/boards/{second_id}/items", headers=auth_headers).json()) == 1

        # The existing flat-library unsave operation must not affect board membership.
        unsave = client.delete(f"/api/v1/research/scraped-ads/{ad.id}/save", headers=auth_headers)
        assert unsave.status_code == 200
        assert db_session.query(ScrapedAd).filter(ScrapedAd.id == ad.id).one().is_saved is False
        assert len(client.get(f"/api/v1/research/boards/{second_id}/items", headers=auth_headers).json()) == 1

        # Board deletion removes only join rows; the ad remains in the database.
        delete_board = client.delete(f"/api/v1/research/boards/{second_id}", headers=auth_headers)
        assert delete_board.status_code == 200
        assert db_session.query(ResearchBoardItem).filter(ResearchBoardItem.board_id == second_id).count() == 0
        assert db_session.query(ScrapedAd).filter(ScrapedAd.id == ad.id).one() is not None

        # Remove the first board and test ad so this test is isolated in shared DB runs.
        client.delete(f"/api/v1/research/boards/{first_id}", headers=auth_headers)
        db_session.query(ScrapedAd).filter(ScrapedAd.id == ad.id).delete()
        db_session.commit()


class TestResearchTestBacklog:
    def test_backlog_keeps_retained_source_context_and_allows_buyer_status_updates(self, client, auth_headers, db_session):
        """A research test is a buyer-owned decision, not a performance claim."""
        ad = create_test_ad(db_session, vertical_name="Commercial Insurance")
        create = client.post(
            "/api/v1/research/test-backlog",
            json={
                "vertical_id": "commercial_insurance",
                "advertiser": ad.brand_name,
                "scraped_ad_id": ad.id,
                "hypothesis": "Test an original proof-led commercial insurance angle.",
            },
            headers=auth_headers,
        )
        assert create.status_code == 201
        item_id = create.json()["id"]

        listed = client.get("/api/v1/research/test-backlog", headers=auth_headers)
        assert listed.status_code == 200
        item = next(row for row in listed.json() if row["id"] == item_id)
        assert item["status"] == "draft"
        assert item["source"]["id"] == ad.id
        assert item["source"]["brand_name"] == ad.brand_name

        update = client.patch(
            f"/api/v1/research/test-backlog/{item_id}",
            json={"status": "building"},
            headers=auth_headers,
        )
        assert update.status_code == 200
        assert update.json()["status"] == "building"

        cross_vertical_ad = create_test_ad(db_session, vertical_name="Auto Insurance")
        cross_vertical = client.post(
            "/api/v1/research/test-backlog",
            json={
                "vertical_id": "commercial_insurance",
                "advertiser": cross_vertical_ad.brand_name,
                "scraped_ad_id": cross_vertical_ad.id,
                "hypothesis": "This must not cross research verticals.",
            },
            headers=auth_headers,
        )
        assert cross_vertical.status_code == 400

        db_session.query(ResearchTestBacklogItem).filter(ResearchTestBacklogItem.id == item_id).delete()
        db_session.query(ScrapedAd).filter(ScrapedAd.id == ad.id).delete()
        db_session.query(ScrapedAd).filter(ScrapedAd.id == cross_vertical_ad.id).delete()
        db_session.query(SavedSearch).filter(SavedSearch.id.in_([ad.search_id, cross_vertical_ad.search_id])).delete(synchronize_session=False)
        db_session.commit()
