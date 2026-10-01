"""Critical acceptance checks using an isolated SQLite database and no LLM calls."""
from __future__ import annotations

import os
import secrets
import sys
import json
import sqlite3
import tempfile
import time
import uuid
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


_test_dir = tempfile.TemporaryDirectory(prefix="sage-acceptance-")
if __package__ != "tests":
    os.environ["SAGE_DATABASE_URL"] = f"sqlite:///{Path(_test_dir.name) / 'test.db'}"
if "app.db" in sys.modules and sys.modules["app.db"].DATABASE_URL != os.environ["SAGE_DATABASE_URL"]:
    raise RuntimeError("测试数据库必须在首次导入 app.db 前配置；请用 unittest discover -s tests -t .")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.models import Assessment, BackgroundTask, QuestionSession, TicketSession, TrainingEnrollment, User  # noqa: E402
from app.cli import backup_sqlite, create_admin, create_member  # noqa: E402
from app.api.auth import _verify_password  # noqa: E402
from app.services.assessment import _score_open_question, run_assessment  # noqa: E402
from app.schemas.assessment import AnswerItem, LearningPlan  # noqa: E402
from app.services.question_gen import _validate_questions, generate_questions  # noqa: E402
from app.services.tasks import _public_error, create_task, enqueue_task, mark_interrupted_tasks  # noqa: E402
from app.services.rag import KnowledgeDocument, KnowledgeRetriever, load_knowledge_documents  # noqa: E402


class SecurityFlowTests(unittest.TestCase):
    def test_knowledge_review_publish_archive_and_profile_scope(self) -> None:
        with SessionLocal() as db:
            ticket = TicketSession(user_id=self.demo["user_id"], profile_id="big_data",
                                   service_id="glue", status="closed", category="troubleshooting",
                                   persona_id="novice_pm", customer_name="simulated customer",
                                   case_id="test-case", model_id="test-model")
            db.add(ticket)
            db.commit()
            ticket_id = ticket.id
        payload = {"profile_id": "big_data", "service_id": "glue", "capability_id": "",
                   "source_type": "case", "title": "Glue 教学案例待审核",
                   "url": "", "source_ticket_id": ticket_id,
                   "details": {key: "已核对的模拟排查内容" for key in
                               ("symptom", "investigation", "root_cause", "resolution", "verification")}}
        member = self._headers(self.demo)
        manager = self._headers(self.admin)
        invalid_scope = {**payload, "profile_id": "analytics"}
        self.assertEqual(self.client.post("/api/knowledge", json=invalid_scope,
                                          headers=member).status_code, 422)
        created = self.client.post("/api/knowledge", json=payload, headers=member)
        self.assertEqual(created.status_code, 201, created.text)
        entry_id = created.json()["id"]
        self.assertEqual(created.json()["status"], "submitted")
        self.assertEqual(self.client.post(f"/api/knowledge/{entry_id}/publish",
                                          headers=member).status_code, 403)
        self.assertFalse(any(doc.document_id == f"managed:{entry_id}"
                             for doc in load_knowledge_documents()))
        self.assertEqual(self.client.get("/api/knowledge?profile_id=analytics",
                                         headers=manager).json(), [])
        self.assertNotIn(entry_id, [item["id"] for item in self.client.get(
            "/api/knowledge", headers=self._headers(self.alice)).json()])

        def mark_pending():
            load_knowledge_documents.cache_clear()
            return "pending"

        with patch("app.api.knowledge._refresh_index", side_effect=mark_pending):
            published = self.client.post(f"/api/knowledge/{entry_id}/publish", headers=manager)
            self.assertEqual(published.status_code, 200, published.text)
            self.assertEqual(published.json()["status"], "published")
            self.assertTrue(any(doc.document_id == f"managed:{entry_id}"
                                for doc in load_knowledge_documents()))
            archived = self.client.post(f"/api/knowledge/{entry_id}/archive", headers=manager)
            self.assertEqual(archived.status_code, 200, archived.text)
            self.assertFalse(any(doc.document_id == f"managed:{entry_id}"
                                 for doc in load_knowledge_documents()))

    def test_official_knowledge_requires_verified_capture(self) -> None:
        manager = self._headers(self.admin)
        payload = {"profile_id": "big_data", "service_id": "glue", "capability_id": "",
                   "source_type": "official_doc", "title": "Glue 官方网络配置资料",
                   "url": "https://docs.amazonaws.cn/zh_cn/glue/latest/dg/start-connecting.html",
                   "details": {}}
        self.assertEqual(self.client.post("/api/knowledge", json={**payload,
            "details": {"text": "fake official body"}}, headers=manager).status_code, 422)
        self.assertEqual(self.client.post("/api/knowledge", json={**payload,
            "url": "https://example.com/fake"}, headers=manager).status_code, 422)
        self.assertEqual(self.client.post("/api/knowledge", json=payload,
                                          headers=self._headers(self.demo)).status_code, 403)
        created = self.client.post("/api/knowledge", json=payload, headers=manager)
        self.assertEqual(created.status_code, 201, created.text)
        entry_id = created.json()["id"]
        self.assertEqual(self.client.post(f"/api/knowledge/{entry_id}/publish",
                                          headers=manager).status_code, 422)
        with patch("app.api.knowledge.preferred_official_source",
                   return_value=(payload["url"], "已核验的 AWS 官方正文。" * 12)), \
             patch("app.api.knowledge._refresh_index", return_value="pending"):
            captured = self.client.post(f"/api/knowledge/{entry_id}/capture", headers=manager)
            self.assertEqual(captured.status_code, 200, captured.text)
            self.assertGreater(captured.json()["chunk_count"], 0)
            published = self.client.post(f"/api/knowledge/{entry_id}/publish", headers=manager)
            self.assertEqual(published.status_code, 200, published.text)

            duplicate = self.client.post("/api/knowledge", json=payload, headers=manager)
            duplicate_id = duplicate.json()["id"]
            self.assertEqual(self.client.post(f"/api/knowledge/{duplicate_id}/capture",
                              headers=manager).status_code, 200)
            self.assertEqual(self.client.post(f"/api/knowledge/{duplicate_id}/publish",
                              headers=manager).status_code, 409)
            version = self.client.post("/api/knowledge", json={**payload, "replaces_entry_id": entry_id},
                                       headers=manager)
            self.assertEqual(version.status_code, 201, version.text)
            version_id = version.json()["id"]
            self.assertEqual(self.client.post(f"/api/knowledge/{version_id}/capture",
                              headers=manager).status_code, 200)
            self.assertEqual(self.client.post(f"/api/knowledge/{version_id}/publish",
                              headers=manager).status_code, 200)
            with SessionLocal() as db:
                from app.models import KnowledgeEntry
                self.assertEqual(db.get(KnowledgeEntry, entry_id).status, "archived")
                self.assertEqual(db.get(KnowledgeEntry, version_id).status, "published")

    def test_new_account_must_change_initial_password(self) -> None:
        username = "initial_" + uuid.uuid4().hex[:8]
        created = self.client.post("/api/admin/users", json={"username": username,
                                   "password": "temporary-pass-123", "role": "member"},
                                   headers=self._headers(self.admin))
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json()["must_change_password"])
        login = self.client.post("/api/auth/login", json={"username": username, "password": "temporary-pass-123"})
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["must_change_password"])
        headers = {"Authorization": "Bearer " + login.json()["token"]}
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/assessment/team-radar", headers=headers).status_code, 403)
        changed = self.client.put("/api/auth/change-password", json={"current_password": "temporary-pass-123",
                                  "new_password": "new-private-pass-123"}, headers=headers)
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)
        relogin = self.client.post("/api/auth/login", json={"username": username, "password": "new-private-pass-123"})
        self.assertEqual(relogin.status_code, 200)
        self.assertFalse(relogin.json()["must_change_password"])

    def test_manager_dashboard_distinguishes_missing_and_reference_evidence(self) -> None:
        username = "board_" + uuid.uuid4().hex[:8]
        with SessionLocal() as db:
            member = User(username=username, display_name="Dashboard QA", role="member",
                          password_hash="unused", current_profile="big_data")
            db.add(member)
            db.commit()
            member_id = member.id
            db.add(Assessment(user_id=member_id, profile_id="big_data", service_id="glue",
                              questions_snapshot=[], question_results=[], kind="pre"))
            db.add(Assessment(user_id=member_id, profile_id="analytics", service_id="kinesis",
                              questions_snapshot=[], question_results=[], kind="pre"))
            db.commit()
        headers = self._headers(self.admin)
        board = self.client.get("/api/admin/dashboard?profile_id=big_data&days=0&include_demo=false&enrolled_only=false", headers=headers)
        self.assertEqual(board.status_code, 200)
        self.assertEqual(self.client.get("/api/admin/dashboard?days=7", headers=headers).status_code, 422)
        target = next(row for row in board.json()["members"] if row["user_id"] == member_id)
        cells = {row["service_id"]: row for row in target["services"]}
        self.assertEqual(cells["glue"]["state"], "reference")
        self.assertEqual(cells["emr"]["state"], "untested")
        self.assertIsNone(cells["emr"]["score"])
        detail = self.client.get(f"/api/admin/members/{member_id}?profile_id=big_data", headers=headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual({row["service_id"] for row in detail.json()["assessments"]}, {"glue"})
        record_id = detail.json()["assessments"][0]["id"]
        self.assertEqual(self.client.get(f"/api/admin/members/{member_id}/assessments/{record_id}?profile_id=big_data", headers=headers).status_code, 200)
        self.assertEqual(self.client.get(f"/api/admin/members/{member_id}/assessments/{record_id}?profile_id=analytics", headers=headers).status_code, 404)
        self.assertEqual(self.client.get("/api/admin/dashboard", headers=self._headers(self.demo)).status_code, 403)
        self.assertEqual(self.client.get(f"/api/admin/members/{member_id}", headers=self._headers(self.demo)).status_code, 403)
        status = self.client.patch(f"/api/admin/users/{member_id}/status", json={"is_demo": True}, headers=headers)
        self.assertEqual(status.status_code, 200)
        board = self.client.get("/api/admin/dashboard", headers=headers).json()
        self.assertNotIn(member_id, {row["user_id"] for row in board["members"]})
        board = self.client.get("/api/admin/dashboard?include_demo=true", headers=headers).json()
        self.assertIn(member_id, {row["user_id"] for row in board["members"]})
        enrolled = self.client.put(f"/api/admin/enrollments/{member_id}",
                                   json={"profile_id": "big_data", "enrolled": True}, headers=headers)
        self.assertEqual(enrolled.status_code, 200)
        self.assertIn(member_id, self.client.get("/api/admin/enrollments?profile_id=big_data", headers=headers).json()["user_ids"])
        self.assertNotIn(member_id, self.client.get("/api/admin/enrollments?profile_id=analytics", headers=headers).json()["user_ids"])
        scoped = self.client.get("/api/admin/dashboard?include_demo=true&enrolled_only=true", headers=headers).json()
        self.assertIn(member_id, {row["user_id"] for row in scoped["members"]})

    def test_admin_cannot_disable_self_and_disabled_member_loses_access(self) -> None:
        headers = self._headers(self.admin)
        response = self.client.patch(f"/api/admin/users/{self.admin['user_id']}/status",
                                     json={"is_active": False}, headers=headers)
        self.assertEqual(response.status_code, 400)
        member_id = self.alice["user_id"]
        disabled = self.client.patch(f"/api/admin/users/{member_id}/status",
                                     json={"is_active": False}, headers=headers)
        self.assertEqual(disabled.status_code, 200)
        try:
            self.assertEqual(self.client.get("/api/auth/me", headers=self._headers(self.alice)).status_code, 403)
            self.assertEqual(self.client.post("/api/auth/login", json={"username": "alice", "password": self.alice_password}).status_code, 403)
            self.assertEqual(self.client.post("/api/auth/login", json={"username": "alice", "password": "wrong"}).status_code, 401)
        finally:
            self.client.patch(f"/api/admin/users/{member_id}/status", json={"is_active": True}, headers=headers)
            type(self).alice = self._login("alice", self.alice_password)

    def test_history_archive_is_owner_scoped_and_paged(self) -> None:
        own = self.client.get(f"/api/assessment/archive/{self.demo['user_id']}?category=assessments&limit=1&offset=0",
                              headers=self._headers(self.demo))
        self.assertEqual(own.status_code, 200)
        self.assertLessEqual(len(own.json()["items"]), 1)
        self.assertIn("total", own.json())
        plans = self.client.get(f"/api/assessment/archive/{self.demo['user_id']}?category=plans&limit=1",
                                headers=self._headers(self.demo))
        self.assertEqual(plans.status_code, 200)
        self.assertIn("total", plans.json())
        denied = self.client.get(f"/api/assessment/archive/{self.alice['user_id']}?category=plans",
                                 headers=self._headers(self.demo))
        self.assertEqual(denied.status_code, 403)
        invalid = self.client.get(f"/api/assessment/archive/{self.demo['user_id']}?category=unknown",
                                  headers=self._headers(self.demo))
        self.assertEqual(invalid.status_code, 422)
        tickets = self.client.get("/api/practice/tickets?limit=1&offset=0", headers=self._headers(self.demo))
        self.assertEqual(tickets.status_code, 200)
        self.assertLessEqual(len(tickets.json()["tickets"]), 1)
        self.assertIn("total", tickets.json())

    def test_completed_learning_plan_stays_in_archive(self) -> None:
        pre_id, post_id = uuid.uuid4().hex, uuid.uuid4().hex
        with SessionLocal() as db:
            db.add(Assessment(id=pre_id, user_id=self.demo["user_id"], service_id="glue",
                              kind="pre", learning_plan={"plan_name": "归档测试计划", "weekly_plan": []},
                              questions_snapshot=[], question_results=[]))
            db.add(Assessment(id=post_id, user_id=self.demo["user_id"], service_id="glue",
                              kind="post", prev_assessment_id=pre_id,
                              questions_snapshot=[], question_results=[]))
            db.commit()
        response = self.client.get(f"/api/assessment/archive/{self.demo['user_id']}?category=plans&limit=50",
                                   headers=self._headers(self.demo))
        self.assertEqual(response.status_code, 200)
        archived = next(item for item in response.json()["items"] if item["assessment_id"] == pre_id)
        self.assertEqual(archived["status"], "completed")
        self.assertEqual(archived["plan_name"], "归档测试计划")

    def test_switching_profile_hides_other_profile_records_and_details(self) -> None:
        glue_id, vpc_id, ticket_id, task_id = (uuid.uuid4().hex for _ in range(4))
        with SessionLocal() as db:
            user = db.get(User, self.demo["user_id"])
            original = user.current_profile
            user.current_profile = "big_data"
            db.add(Assessment(id=glue_id, user_id=user.id, profile_id="big_data", service_id="glue",
                              kind="pre", learning_plan={"plan_name": "Glue plan", "weekly_plan": []},
                              questions_snapshot=[], question_results=[]))
            db.add(Assessment(id=vpc_id, user_id=user.id, profile_id="networking", service_id="vpc",
                              kind="pre", learning_plan={"plan_name": "VPC plan", "weekly_plan": []},
                              questions_snapshot=[], question_results=[]))
            db.add(TicketSession(id=ticket_id, user_id=user.id, profile_id="networking", service_id="vpc",
                                 category="troubleshooting", persona_id="novice_pm", customer_name="test",
                                 case_id="test", case_data={"title": "VPC test ticket"}, model_id="test"))
            db.add(BackgroundTask(id=task_id, user_id=user.id, profile_id="big_data",
                                  status="done", job_kind="generate", payload={}, result={"value": 1}))
            db.commit()
        headers = self._headers(self.demo)
        try:
            big = self.client.get(f"/api/assessment/archive/{self.demo['user_id']}?category=plans&limit=50", headers=headers)
            ids = {item["assessment_id"] for item in big.json()["items"]}
            self.assertIn(glue_id, ids)
            self.assertNotIn(vpc_id, ids)
            profile_url = f"/api/assessment/users/{self.demo['user_id']}/profile-insights"
            self.assertEqual(self.client.get(profile_url).status_code, 401)
            self.assertEqual(self.client.get(
                f"/api/assessment/users/{self.alice['user_id']}/profile-insights",
                headers=headers).status_code, 403)
            big_profile = self.client.get(profile_url, headers=headers)
            self.assertEqual(big_profile.status_code, 200)
            self.assertEqual(big_profile.json()["profile_id"], "big_data")
            self.assertIn(glue_id, {item["assessment_id"] for item in big_profile.json()["recent_assessments"]})
            self.assertNotIn(vpc_id, {item["assessment_id"] for item in big_profile.json()["recent_assessments"]})
            self.assertEqual(self.client.get(f"/api/assessment/results/{vpc_id}", headers=headers).status_code, 404)
            self.assertEqual(self.client.get(f"/api/practice/tickets/{ticket_id}", headers=headers).status_code, 404)
            self.assertEqual(self.client.get(f"/api/learning/plans/{vpc_id}/progress", headers=headers).status_code, 404)
            self.assertEqual(self.client.get(f"/api/assessment/task/{task_id}", headers=headers).status_code, 200)
            with SessionLocal() as db:
                db.get(User, self.demo["user_id"]).current_profile = "networking"
                db.commit()
            network = self.client.get(f"/api/assessment/archive/{self.demo['user_id']}?category=plans&limit=50", headers=headers)
            ids = {item["assessment_id"] for item in network.json()["items"]}
            self.assertIn(vpc_id, ids)
            self.assertNotIn(glue_id, ids)
            network_profile = self.client.get(profile_url, headers=headers)
            self.assertEqual(network_profile.status_code, 200)
            self.assertEqual(network_profile.json()["profile_id"], "networking")
            self.assertIn(vpc_id, {item["assessment_id"] for item in network_profile.json()["recent_assessments"]})
            self.assertNotIn(glue_id, {item["assessment_id"] for item in network_profile.json()["recent_assessments"]})
            self.assertEqual(self.client.get(f"/api/assessment/results/{glue_id}", headers=headers).status_code, 404)
            self.assertEqual(self.client.get(f"/api/learning/plans/{glue_id}/progress", headers=headers).status_code, 404)
            self.assertEqual(self.client.get(f"/api/assessment/task/{task_id}", headers=headers).status_code, 404)
            tickets = self.client.get("/api/practice/tickets", headers=headers).json()
            self.assertIn(ticket_id, {item["ticket_id"] for item in tickets["tickets"]})
        finally:
            with SessionLocal() as db:
                db.get(User, self.demo["user_id"]).current_profile = original
                db.commit()

    def test_legacy_assessment_profile_is_backfilled_from_unique_service(self) -> None:
        assessment_id = uuid.uuid4().hex
        with SessionLocal() as db:
            db.add(Assessment(id=assessment_id, user_id=self.demo["user_id"], service_id="glue",
                              kind="pre", questions_snapshot=[], question_results=[]))
            db.commit()
        init_db()
        with SessionLocal() as db:
            self.assertEqual(db.get(Assessment, assessment_id).profile_id, "big_data")

    def test_question_generation_cannot_bind_service_to_wrong_profile(self) -> None:
        with self.assertRaisesRegex(ValueError, "不属于指定 Profile"):
            generate_questions(service_id="glue", profile_id="networking", user_id=self.demo["user_id"])

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.demo_password = secrets.token_urlsafe(18)
        cls.alice_password = secrets.token_urlsafe(18)
        cls.admin_password = secrets.token_urlsafe(18)
        create_member("demo", cls.demo_password)
        create_member("alice", cls.alice_password)
        create_admin("admin", cls.admin_password)
        cls.demo = cls._login("demo", cls.demo_password)
        cls.alice = cls._login("alice", cls.alice_password)
        cls.admin = cls._login("admin", cls.admin_password)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        engine.dispose()
        _test_dir.cleanup()

    @classmethod
    def _login(cls, username: str, password: str) -> dict:
        response = cls.client.post("/api/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return response.json()

    @staticmethod
    def _headers(user: dict) -> dict:
        return {"Authorization": f"Bearer {user['token']}"}

    def test_team_and_user_data_are_protected(self) -> None:
        self.assertEqual(self.client.get("/api/assessment/team-radar").status_code, 401)
        self.assertEqual(self.client.get("/api/assessment/team-radar", headers=self._headers(self.demo)).status_code, 403)
        self.assertEqual(self.client.get("/api/assessment/team-radar", headers=self._headers(self.admin)).status_code, 200)
        path = f"/api/assessment/history/{self.alice['user_id']}"
        self.assertEqual(self.client.get(path, headers=self._headers(self.demo)).status_code, 403)
        self.assertEqual(self.client.get("/api/llm/ping").status_code, 401)
        self.assertEqual(self.client.get("/api/llm/ping", headers=self._headers(self.demo)).status_code, 403)
        with patch("app.main.settings.llm_api_key", ""):
            self.assertEqual(self.client.get("/api/llm/ping", headers=self._headers(self.admin)).status_code, 503)
        allowed = self.client.get("/health", headers={"Origin": "http://127.0.0.1:3000"})
        denied = self.client.get("/health", headers={"Origin": "https://untrusted.example"})
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "http://127.0.0.1:3000")
        self.assertIsNone(denied.headers.get("access-control-allow-origin"))

    def test_model_discovery_is_authenticated_and_never_returns_credentials(self) -> None:
        from app.services.llm import get_available_models

        with patch("app.services.llm.get_settings") as settings, \
             patch("app.services.llm.get_llm") as llm:
            settings.return_value.llm_api_key = "test-only-secret"
            settings.return_value.llm_model = "configured-model"
            llm.return_value.list_models.return_value = ["new-model", "configured-model"]
            self.assertEqual(self.client.get("/api/llm/models").status_code, 401)
            response = self.client.get("/api/llm/models", headers=self._headers(self.demo))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["models"], ["configured-model", "new-model"])
            self.assertTrue(response.json()["discovery_available"])
            self.assertNotIn("test-only-secret", response.text)

            llm.return_value.list_models.side_effect = RuntimeError("provider error with credentials")
            fallback = get_available_models()
            self.assertEqual(fallback["models"], ["configured-model"])
            self.assertFalse(fallback["discovery_available"])
            self.assertNotIn("credentials", str(fallback))

    def test_admin_provisioning_has_no_default_password_or_role_upgrade(self) -> None:
        with self.assertRaises(ValueError):
            create_admin("lead", "short")
        admin_id = create_admin("lead", "a-long-private-password", "Team lead")
        with SessionLocal() as db:
            user = db.get(User, admin_id)
            self.assertEqual(user.role, "manager")
            self.assertTrue(user.password_hash.startswith("pbkdf2_sha256$"))
            self.assertTrue(_verify_password("a-long-private-password", user.password_hash))
        with self.assertRaises(ValueError):
            create_admin("lead", "another-long-password")
        member_id = create_member("new_member", "another-long-password")
        with SessionLocal() as db:
            self.assertEqual(db.get(User, member_id).role, "member")

    def test_production_registration_is_disabled_by_default(self) -> None:
        from app.api.auth import _registration_enabled
        with patch("app.api.auth.get_settings") as settings:
            settings.return_value.app_env = "production"
            settings.return_value.public_registration = False
            self.assertFalse(_registration_enabled())
            self.assertEqual(self.client.post("/api/auth/register", json={
                "username": "public_person", "password": "long-password"}).status_code, 403)
            self.assertEqual(self.client.get("/api/auth/config").json()["registration_enabled"], False)

    def test_login_throttle_blocks_repeated_failures_and_success_resets(self) -> None:
        for _ in range(4):
            response = self.client.post("/api/auth/login", json={"username": "unknown-brute-force", "password": "wrong"})
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "unknown-brute-force", "password": "wrong"}).status_code, 429)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "unknown-brute-force", "password": "wrong"}).status_code, 429)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "demo", "password": "incorrect"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "demo", "password": self.demo_password}).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "demo", "password": "incorrect"}).status_code, 401)

    def test_sqlite_backup_is_consistent_and_does_not_overwrite(self) -> None:
        destination = Path(_test_dir.name) / "backup.db"
        self.assertEqual(backup_sqlite(str(destination)), destination)
        with sqlite3.connect(destination) as connection:
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            backup_sqlite(str(destination))

    def test_assessment_refuses_missing_llm_without_creating_task(self) -> None:
        with patch("app.api.assessment.get_settings") as settings:
            settings.return_value.llm_api_key = ""
            response = self.client.post("/api/assessment/generate", headers=self._headers(self.demo),
                json={"service_id": "glue", "num_choice": 6, "num_open": 3})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("task_id", response.text)

    def test_assessment_rejects_model_not_in_discovery_before_creating_task(self) -> None:
        with patch("app.api.assessment.get_settings") as settings, \
             patch("app.api.assessment.resolve_generation_model", side_effect=ValueError("所选模型当前不可用，请刷新模型列表后重试")):
            settings.return_value.llm_api_key = "test-only"
            response = self.client.post("/api/assessment/generate", headers=self._headers(self.demo),
                json={"service_id": "glue", "model_id": "stale-model"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("task_id", response.text)

    def test_question_answers_remain_server_side(self) -> None:
        with SessionLocal() as db:
            db.add(QuestionSession(id="question-fixture", user_id=self.demo["user_id"],
                                   service_id="glue", questions=[{
                                       "id": "q1", "type": "choice", "dimension_id": "cap",
                                       "question": "Example?", "options": ["one", "two"],
                                       "correct_answer": "A", "reference_answer": "one",
                                       "scoring_rubric": ["one"]}]))
            db.commit()
        path = "/api/assessment/sessions/question-fixture"
        response = self.client.get(path, headers=self._headers(self.demo))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("correct_answer", response.text)
        self.assertNotIn("reference_answer", response.text)
        self.assertEqual(self.client.get(path, headers=self._headers(self.alice)).status_code, 404)

    def test_invalid_llm_score_never_becomes_a_low_score(self) -> None:
        question = {"difficulty": "L1", "question": "Example?", "scoring_rubric": ["one"]}
        with patch("app.services.assessment.get_llm") as llm:
            llm.return_value.chat.return_value = "not json"
            with self.assertRaises(ValueError):
                _score_open_question(question, "a submitted answer")

    def test_partial_question_set_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _validate_questions([{"id": "q1", "type": "choice", "difficulty": "L1"}], {"glue_network"})

    def test_mocked_full_pre_and_post_assessment_flow(self) -> None:
        questions = []
        for index, level in enumerate(["L1", "L1", "L2", "L2", "L3", "L3"], start=1):
            questions.append({"id": f"q{index}", "type": "choice", "dimension_id": "glue_network",
                "difficulty": level, "question": f"网络知识点 {index}？", "options": ["one", "two", "three", "four"],
                "correct_answer": "A", "multi_select": False, "source_ids": ["vpc_nat"]})
        for index, level in enumerate(["L1", "L2", "L3"], start=7):
            questions.append({"id": f"q{index}", "type": "open", "dimension_id": "glue_network",
                "difficulty": level, "question": f"解释网络机制 {index}",
                "scoring_rubric": ["机制", "配置", "验证"], "reference_answer": "参考答案",
                "source_ids": ["vpc_nat"]})
        answers = [{"question_id": q["id"], "answer": "A" if q["type"] == "choice" else "说明网络机制和验证方法"}
                   for q in questions]

        def wait_for(task_id: str) -> dict:
            for _ in range(100):
                response = self.client.get(f"/api/assessment/task/{task_id}", headers=self._headers(self.alice))
                if response.json()["status"] in {"done", "error"}:
                    return response.json()
                time.sleep(0.02)
            self.fail("mocked assessment task did not finish")

        with (patch("app.api.assessment.get_settings") as settings,
              patch("app.api.assessment.resolve_generation_model",
                    side_effect=lambda model_id: model_id or "configured-model"),
              patch("app.services.question_gen.retrieve_resources", return_value=[]) as retrieve,
              patch("app.services.question_gen.get_llm") as llm,
              patch("app.services.assessment._score_open_question", return_value={
                  "scores": {"accuracy": 4}, "avg_score": 4, "total_score": 20,
                  "level": "L2", "feedback": "ok"}) as scorer,
              patch("app.services.assessment.run_post_scoring_pipeline", return_value=(
                  [], LearningPlan(plan_name="Mock plan"), None, [], [])) as pipeline):
            settings.return_value.llm_api_key = "test-only"
            llm.return_value.chat.return_value = json.dumps({"questions": questions}, ensure_ascii=False)
            generated = wait_for(self.client.post("/api/assessment/generate", json={
                "service_id": "glue", "model_id": "test-generation-model",
                "study_days": 2, "minutes_per_day": 45},
                headers=self._headers(self.alice)).json()["task_id"])
            self.assertEqual(generated["status"], "done")
            retrieve.assert_called_once()
            self.assertEqual(retrieve.call_args.kwargs["service_id"], "glue")
            llm.return_value.chat.assert_called_once()
            self.assertEqual(llm.return_value.chat.call_args.kwargs["model"], "test-generation-model")
            self.assertEqual(len(generated["result"]["questions"]), 9)
            self.assertNotIn("correct_answer", str(generated["result"]["questions"]))
            self.assertNotIn("source_refs", str(generated["result"]["questions"]))
            session_id = generated["result"]["session_id"]
            from app.services.question_gen import generate_questions, get_session
            stored_session = get_session(session_id, self.alice["user_id"])
            self.assertEqual(stored_session["study_days"], 2)
            self.assertEqual(stored_session["minutes_per_day"], 45)
            repeated_id, repeated_questions = generate_questions(
                "glue", user_id=self.alice["user_id"], model_id="test-generation-model",
                study_days=2, minutes_per_day=45, session_id=session_id)
            self.assertEqual(repeated_id, session_id)
            self.assertEqual(repeated_questions, stored_session["questions"])
            llm.return_value.chat.assert_called_once()
            pre = wait_for(self.client.post("/api/assessment/submit",
                json={"session_id": session_id, "answers": answers},
                headers=self._headers(self.alice)).json()["task_id"])
            self.assertEqual(pre["status"], "done")
            self.assertEqual(pre["result"]["model_id"], "test-generation-model")
            self.assertTrue(all(call.kwargs["model"] == "test-generation-model"
                                for call in scorer.call_args_list))
            self.assertEqual(pipeline.call_args.kwargs["model"], "test-generation-model")
            self.assertEqual(pipeline.call_args.kwargs["study_days"], 2)
            self.assertEqual(pipeline.call_args.kwargs["minutes_per_day"], 45)
            pre_id = pre["result"]["assessment_id"]
            self.assertEqual(self.client.get(f"/api/assessment/results/{pre_id}",
                headers=self._headers(self.alice)).status_code, 200)
            post_generated = wait_for(self.client.post("/api/assessment/post-test/generate",
                json={"prev_assessment_id": pre_id}, headers=self._headers(self.alice)).json()["task_id"])
            self.assertEqual(post_generated["status"], "done")
            post_session = post_generated["result"]["session_id"]
            post = wait_for(self.client.post("/api/assessment/post-test/submit",
                json={"session_id": f"{post_session}:{pre_id}", "answers": answers},
                headers=self._headers(self.alice)).json()["task_id"])
            self.assertEqual(post["status"], "done")
            self.assertEqual(post["result"]["kind"], "post")
            self.assertIsNotNone(post["result"]["prev_capability_radar"])

    def test_agent_failure_is_explicit_and_submission_idempotent(self) -> None:
        with SessionLocal() as db:
            db.add(QuestionSession(id="pipeline-fixture", user_id=self.demo["user_id"],
                service_id="glue", questions=[{"id": "choice-1", "type": "choice",
                    "dimension_id": "glue_network", "question": "Example?",
                    "options": ["one", "two"], "correct_answer": "A"}]))
            db.commit()
        answers = [AnswerItem(question_id="choice-1", answer="A")]
        with patch("app.services.assessment.run_post_scoring_pipeline", side_effect=RuntimeError("offline")):
            first = run_assessment(self.demo["user_id"], answers, "pipeline-fixture")
        self.assertIsNone(first.learning_plan)
        self.assertEqual(first.agent_trace[0].status, "failed")
        again = run_assessment(self.demo["user_id"], answers, "pipeline-fixture")
        self.assertEqual(first.assessment_id, again.assessment_id)

    def test_task_result_is_repeatable_and_private(self) -> None:
        task_id = create_task(lambda: {"value": 7}, user_id=self.demo["user_id"])
        path = f"/api/assessment/task/{task_id}"
        self.assertEqual(self.client.get(path, headers=self._headers(self.alice)).status_code, 404)
        for _ in range(30):
            response = self.client.get(path, headers=self._headers(self.demo))
            if response.json()["status"] == "done":
                break
            time.sleep(0.02)
        self.assertEqual(response.json()["result"], {"value": 7})
        self.assertEqual(self.client.get(path, headers=self._headers(self.demo)).json()["result"], {"value": 7})

    def test_saved_job_replays_and_submit_idempotency_is_owner_scoped(self) -> None:
        payload = {"session_id": "replay-fixture", "answers": []}
        with patch("app.services.tasks._execute_job", return_value={"value": 9}) as execute:
            task_id = enqueue_task("submit", payload, user_id=self.demo["user_id"],
                                   idempotency_key="replay-fixture")
            for _ in range(100):
                if self.client.get(f"/api/assessment/task/{task_id}",
                                   headers=self._headers(self.demo)).json()["status"] == "done":
                    break
                time.sleep(0.02)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(enqueue_task("submit", payload, user_id=self.demo["user_id"],
                                          idempotency_key="replay-fixture"), task_id)
            self.assertEqual(execute.call_count, 1)
            self.assertIsNone(__import__("app.services.tasks", fromlist=["get_task"]).get_task(
                task_id, user_id=self.alice["user_id"]))
            with SessionLocal() as db:
                from app.models import BackgroundTask
                row = db.get(BackgroundTask, task_id)
                row.status, row.result = "running", None
                db.commit()
            mark_interrupted_tasks()
            for _ in range(100):
                data = self.client.get(f"/api/assessment/task/{task_id}",
                                       headers=self._headers(self.demo)).json()
                if data["status"] == "done":
                    break
                time.sleep(0.02)
            self.assertEqual(data["result"], {"value": 9})
            self.assertEqual(execute.call_count, 2)

    def test_failed_learning_can_resume_without_changing_saved_score(self) -> None:
        with SessionLocal() as db:
            db.add(QuestionSession(id="retry-learning-fixture", user_id=self.demo["user_id"],
                service_id="glue", questions=[{"id": "choice-1", "type": "choice",
                    "dimension_id": "glue_network", "question": "Example?",
                    "options": ["one", "two"], "correct_answer": "A"}]))
            db.commit()
        answers = [AnswerItem(question_id="choice-1", answer="A")]
        with patch("app.services.assessment.run_post_scoring_pipeline",
                   side_effect=RuntimeError("temporary failure")):
            before = run_assessment(self.demo["user_id"], answers, "retry-learning-fixture")
        with (patch("app.api.assessment.get_settings") as settings,
              patch("app.services.assessment.run_post_scoring_pipeline",
                    return_value=([], LearningPlan(plan_name="Recovered",
                                                   weekly_plan=[{"week": 1, "focus": "network",
                                                                 "tasks": []}]),
                                  {"status": "passed", "remaining_issues": []}, [], []))):
            settings.return_value.llm_api_key = "test-only"
            response = self.client.post(
                f"/api/assessment/results/{before.assessment_id}/retry-learning",
                headers=self._headers(self.demo))
            self.assertEqual(response.status_code, 200)
            task_id = response.json()["task_id"]
            for _ in range(100):
                data = self.client.get(f"/api/assessment/task/{task_id}",
                                       headers=self._headers(self.demo)).json()
                if data["status"] in {"done", "error"}:
                    break
                time.sleep(0.02)
        self.assertEqual(data["status"], "done")
        self.assertEqual(data["result"]["assessment_id"], before.assessment_id)
        self.assertEqual(data["result"]["choice_score"], before.choice_score)
        self.assertEqual(data["result"]["learning_plan"]["plan_name"], "Recovered")
        self.assertEqual(self.client.post(
            f"/api/assessment/results/{before.assessment_id}/retry-learning",
            headers=self._headers(self.alice)).status_code, 404)

    def test_task_error_is_actionable_but_does_not_leak_unknown_errors(self) -> None:
        def failure() -> None:
            raise ValueError("题目生成失败，请重试")
        with patch("app.services.tasks.logger.exception"):
            task_id = create_task(failure, user_id=self.demo["user_id"])
            for _ in range(30):
                data = self.client.get(f"/api/assessment/task/{task_id}", headers=self._headers(self.demo)).json()
                if data["status"] == "error":
                    break
                time.sleep(0.02)
        self.assertEqual(data["error"], "题目生成失败，请重试")
        self.assertEqual(_public_error(RuntimeError("secret internal details")),
                         "任务执行失败，请重试；已完成的成绩不会被覆盖")

    def test_practice_evidence_and_results_are_private_and_durable(self) -> None:
        self.assertEqual(self.client.get("/api/practice/scenarios").status_code, 401)
        public = self.client.get("/api/practice/scenarios/glue-sg-self-reference",
                                 headers=self._headers(self.demo))
        self.assertEqual(public.status_code, 200)
        self.assertNotIn("自引用规则", public.text)
        self.assertNotIn("evidence", public.text)
        created = self.client.post("/api/practice/runs", json={"scenario_id": "glue-sg-self-reference"},
                                   headers=self._headers(self.demo))
        self.assertEqual(created.status_code, 201)
        run_id = created.json()["run_id"]
        own_runs = self.client.get("/api/practice/runs", headers=self._headers(self.demo)).json()["runs"]
        other_runs = self.client.get("/api/practice/runs", headers=self._headers(self.alice)).json()["runs"]
        self.assertIn(run_id, {item["run_id"] for item in own_runs})
        self.assertNotIn(run_id, {item["run_id"] for item in other_runs})
        path = f"/api/practice/runs/{run_id}"
        self.assertEqual(self.client.get(path, headers=self._headers(self.alice)).status_code, 404)
        self.assertNotIn("evidence", created.text)
        inspect = self.client.post(f"{path}/inspect", json={"tool_id": "security_group"},
                                   headers=self._headers(self.demo))
        self.assertEqual(inspect.status_code, 200)
        self.assertIn("自引用", inspect.json()["evidence"])
        self.assertIn("evidence", self.client.get(path, headers=self._headers(self.demo)).text)
        answer = "安全组缺少自身作为来源的自引用入站规则。应添加来源为自身的所有 TCP 入站规则，然后重新执行 Glue 测试连接并保留结果。"
        submitted = self.client.post(f"{path}/submit", json={"answer": answer}, headers=self._headers(self.demo))
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.json()["feedback"]["score"], 100)
        self.assertEqual(self.client.get(path, headers=self._headers(self.demo)).json()["feedback"]["score"], 100)
        self.assertEqual(self.client.post(f"{path}/inspect", json={"tool_id": "job_log"},
                                          headers=self._headers(self.demo)).status_code, 409)

    def test_second_practice_scenario_uses_its_own_rubric(self) -> None:
        scenarios = self.client.get("/api/practice/scenarios", headers=self._headers(self.demo)).json()["scenarios"]
        self.assertEqual({item["id"] for item in scenarios},
                         {"glue-sg-self-reference", "glue-subnet-ip-exhaustion"})
        public = self.client.get("/api/practice/scenarios/glue-subnet-ip-exhaustion",
                                 headers=self._headers(self.demo))
        self.assertNotIn("rubric", public.text)
        self.assertNotIn("expected", public.text)
        created = self.client.post("/api/practice/runs", json={"scenario_id": "glue-subnet-ip-exhaustion"},
                                   headers=self._headers(self.demo))
        path = f"/api/practice/runs/{created.json()['run_id']}"
        self.client.post(f"{path}/inspect", json={"tool_id": "subnet_status"}, headers=self._headers(self.demo))
        answer = "子网可用 IP 地址不足，导致 Glue 的网络接口无法为 Worker 启动；SparkContext 关闭只是后续表现。应减少 Worker 数量或更换更大子网，随后重新运行作业并核对可用 IP。"
        result = self.client.post(f"{path}/submit", json={"answer": answer}, headers=self._headers(self.demo))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["feedback"]["score"], 100)

    def test_chat_ticket_is_private_and_hides_case_truth_until_finished(self) -> None:
        from app.services.ticket_simulation import get_case
        case = get_case("glue-public-api-nat")
        with patch("app.api.tickets.get_settings") as settings, \
             patch("app.api.tickets.resolve_generation_model", return_value="test-model"), \
             patch("app.api.tickets.choose_case", return_value=case), \
             patch("app.api.tickets.generate_case", return_value=case):
            settings.return_value.llm_api_key = "test-only"
            self.assertEqual(self.client.get("/api/practice/tickets/options").status_code, 401)
            created = self.client.post("/api/practice/tickets", headers=self._headers(self.demo), json={
                "service_id": "glue", "category": "troubleshooting", "persona_id": "engineer"})
        self.assertEqual(created.status_code, 201, created.text)
        ticket_id = created.json()["ticket_id"]
        path = f"/api/practice/tickets/{ticket_id}"
        self.assertNotIn("root_cause", created.text)
        self.assertNotIn("expected", created.text)
        self.assertNotIn("子网缺少可用 NAT 出口", created.text)
        self.assertEqual(self.client.get(path, headers=self._headers(self.alice)).status_code, 404)
        self.assertEqual(self.client.post(path + "/finish", headers=self._headers(self.demo),
                          json={"final_answer": "我认为需要检查路由和安全组，找到实际阻断原因后，在隔离环境修复，并对同一目标做前后验证。"}).status_code, 400)
        with patch("app.api.tickets.customer_turn", return_value={
                "reply": "我查到了日志。", "evidence_ids": ["job_log"],
                "state": {"known_evidence_ids": ["job_log"], "pending_evidence_ids": [],
                          "pending_actions": [], "events": [], "turn": 1, "frustration": 1}}):
            for question in ("请发我作业日志和报错", "它能连接 VPC 内的数据库吗？"):
                reply = self.client.post(path + "/messages", headers=self._headers(self.demo),
                                         json={"message": question})
                self.assertEqual(reply.status_code, 200, reply.text)
        own = self.client.get(path, headers=self._headers(self.demo)).json()
        self.assertEqual(own["turn_count"], 2)
        self.assertIsNone(own["report"])
        fake_report = {"status": "ai_provisional", "overall_score": 80, "dimensions": []}
        with patch("app.api.tickets.grade_ticket", return_value=fake_report):
            finished = self.client.post(path + "/finish", headers=self._headers(self.demo),
                                        json={"final_answer": "当前 Glue 作业缺少 NAT 出口，应先检查私有子网路由，再在隔离环境修正，并对同一公网 API 做前后验证。"})
        self.assertEqual(finished.status_code, 200, finished.text)
        self.assertEqual(finished.json()["report"]["overall_score"], 80)
        self.assertEqual(finished.json()["messages"][-1]["kind"], "final_summary")
        self.assertIn("缺少 NAT 出口", finished.json()["messages"][-1]["content"])
        self.assertEqual(self.client.post(path + "/messages", headers=self._headers(self.demo),
                          json={"message": "再问一句"}).status_code, 409)
        self.assertNotIn(ticket_id, {item["ticket_id"] for item in
                                self.client.get("/api/practice/tickets", headers=self._headers(self.alice)).json()["tickets"]})

    def test_ticket_options_follow_current_profile_and_generated_case_is_frozen(self) -> None:
        options = self.client.get("/api/practice/tickets/options",
                                  headers=self._headers(self.demo)).json()
        self.assertEqual(options["profile_id"], "big_data")
        self.assertEqual({item["id"] for item in options["services"]},
                         {"glue", "emr", "athena", "mwaa", "lake_formation", "sagemaker", "dynamodb"})
        self.assertEqual(len(options["categories"]), 7)
        self.assertEqual(len(options["personas"]), 8)
        self.assertTrue(all("expertise" in item and "patience" in item
                            for item in options["personas"]))

        fake_case = {
            "id": "generated-fixture", "service_id": "emr", "category": "performance",
            "title": "EMR 模拟性能工单", "opening": "虚构训练集群的步骤运行缓慢。",
            "evidence": [{"id": "metric", "label": "指标", "content": "虚构指标显示处理延迟升高。"}],
            "expected": {"background": "训练团队每日运行模拟数据作业。", "scenario": "作业步骤耗时突然增加。",
                         "problem": "步骤运行缓慢", "investigation_steps": ["确认时间线", "收集运行指标", "验证容量假设"],
                         "reasoning": "通过前后对比确认变化并关联容量指标。", "root_cause": "虚构容量不足",
                         "resolution": "调整虚构训练环境容量", "verification": "前后对比指标"},
            "sources": [], "generated": True,
        }
        with patch("app.api.tickets.get_settings") as settings, \
             patch("app.api.tickets.resolve_generation_model", return_value="test-model"), \
             patch("app.api.tickets.generate_case", return_value=fake_case):
            settings.return_value.llm_api_key = "test-only"
            created = self.client.post("/api/practice/tickets", headers=self._headers(self.demo),
                json={"service_id": "emr", "category": "performance",
                      "persona_id": "impatient_owner", "impact": "production_down",
                      "difficulty": "advanced", "cross_service": True})
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body["service_id"], "emr")
        self.assertEqual(body["case_origin"], "generated")
        self.assertEqual(body["difficulty"], "advanced")
        self.assertNotIn("root_cause", created.text)
        with SessionLocal() as db:
            stored = db.get(__import__("app.models", fromlist=["TicketSession"]).TicketSession,
                            body["ticket_id"])
            self.assertEqual(stored.case_data["expected"]["root_cause"], "虚构容量不足")

        rejected = self.client.post("/api/practice/tickets", headers=self._headers(self.demo),
            json={"service_id": "vpc", "category": "troubleshooting",
                  "persona_id": "novice_pm"})
        self.assertEqual(rejected.status_code, 400)

    def test_customer_chat_releases_only_grounded_evidence_and_scoring_is_bounded(self) -> None:
        from app.services.ticket_simulation import customer_reply, get_case, grade_ticket
        case = get_case("glue-public-api-nat")
        with patch("app.services.ticket_dialogue.get_llm") as llm:
            llm.return_value.chat.side_effect = [
                json.dumps({"reply": "我把日志找到了。", "intent": "request_evidence",
                            "evidence_ids": ["job_log", "invented"], "collection_guidance": False,
                            "acknowledges_impact": False, "clear_next_step": False, "action_quote": ""}),
                json.dumps({"supported": True, "reason": "符合已展示信息"})]
            reply, evidence_ids = customer_reply(case, "engineer", "王工", [], "请提供作业日志", "test")
            prompt = llm.return_value.chat.call_args_list[0].args[0]
        self.assertEqual(evidence_ids, ["job_log"])
        self.assertIn("连接阶段超时", reply)
        self.assertNotIn(case["expected"]["root_cause"], json.dumps(prompt, ensure_ascii=False))
        result = {"summary": "需要继续核查", "investigation_steps": [], "strengths": [],
                  "improvements": ["补充证据"], "dimensions": {key: {"score": 5, "reason": "模型建议",
                      "citations": [{"turn": 0, "role": "final", "quote": "我会先检查路由再验证"}],
                      "next_step": "先索取日志并说明获取方式"}
                      for key in ("clarification", "evidence", "technical_judgment", "resolution",
                                  "communication", "verification")}}
        with patch("app.services.ticket_simulation.get_llm") as llm:
            llm.return_value.chat.return_value = json.dumps(result, ensure_ascii=False)
            report = grade_ticket(case, [], "我会先检查路由再验证", [], "test")
        self.assertEqual(next(item["score"] for item in report["dimensions"] if item["id"] == "evidence"), 5)
        self.assertEqual(report["status"], "ai_provisional")
        result["dimensions"].pop("verification")
        with patch("app.services.ticket_simulation.get_llm") as llm:
            llm.return_value.chat.return_value = json.dumps(result, ensure_ascii=False)
            with self.assertRaisesRegex(ValueError, "维度不完整"):
                grade_ticket(case, [], "我会先检查路由再验证", [], "test")

    def test_learning_evidence_is_owned_and_persisted(self) -> None:
        with SessionLocal() as db:
            db.add(Assessment(id="plan-fixture", user_id=self.demo["user_id"], profile_id="big_data", service_id="glue",
                              learning_plan={"weekly_plan": [{"tasks": [{"topic": "Network lab"}]}]}))
            db.commit()
        path = "/api/learning/plans/plan-fixture/progress"
        self.assertEqual(self.client.get(path, headers=self._headers(self.alice)).status_code, 404)
        bad = self.client.put(path, headers=self._headers(self.demo),
                              json={"week_index": 1, "task_index": 0, "evidence": "confirmed by test"})
        self.assertEqual(bad.status_code, 400)
        saved = self.client.put(path, headers=self._headers(self.demo),
                                json={"week_index": 0, "task_index": 0, "evidence": "Confirmed VPC rules in sandbox"})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(len(self.client.get(path, headers=self._headers(self.demo)).json()["progress"]), 1)
        updated = self.client.put(path, headers=self._headers(self.demo),
                                  json={"week_index": 0, "task_index": 0, "evidence": "Retested Glue connection successfully"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(len(self.client.get(path, headers=self._headers(self.demo)).json()["progress"]), 1)
        blocked = self.client.put(path, headers=self._headers(self.demo), json={
            "week_index": 0, "task_index": 0, "status": "blocked",
            "evidence": "测试账号没有相应权限，无法执行 VPC 实验"})
        self.assertEqual(blocked.status_code, 200)
        self.assertEqual(blocked.json()["status"], "blocked")
        self.assertEqual(self.client.get("/api/learning/review-queue?profile_id=big_data",
                         headers=self._headers(self.demo)).status_code, 403)
        submitted = self.client.put(path, headers=self._headers(self.demo), json={
            "week_index": 0, "task_index": 0, "status": "submitted",
            "evidence": "已经在沙箱验证 VPC 路由与安全组设置"})
        self.assertEqual(submitted.status_code, 200)
        queue = self.client.get("/api/learning/review-queue?profile_id=big_data",
                                headers=self._headers(self.admin)).json()["items"]
        row = next(item for item in queue if item["assessment_id"] == "plan-fixture")
        review_url = f"/api/learning/progress/{row['id']}/review"
        self.assertEqual(self.client.put(review_url, headers=self._headers(self.demo), json={
            "accepted": True, "review_note": "实验产出已核对并满足验收要求"}).status_code, 403)
        reviewed = self.client.put(review_url, headers=self._headers(self.admin), json={
            "accepted": True, "review_note": "实验产出已核对并满足验收要求"})
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.json()["status"], "verified")
        self.assertEqual(self.client.put(path, headers=self._headers(self.demo), json={
            "week_index": 0, "task_index": 0, "status": "submitted",
            "evidence": "尝试覆盖已验收证据应该被拒绝"}).status_code, 409)

    def test_quality_feedback_preserves_original_and_is_owner_scoped(self) -> None:
        assessment_id = uuid.uuid4().hex
        with SessionLocal() as db:
            db.add(Assessment(id=assessment_id, user_id=self.demo["user_id"], profile_id="big_data",
                              service_id="glue", questions_snapshot=[{"id": "q1", "question": "Glue?"}],
                              question_results=[{"question_id": "q1", "total_score": 2}], overall_avg=2.0))
            db.commit()
        path = "/api/feedback"
        body = {"record_type": "assessment", "record_id": assessment_id, "question_id": "q1",
                "category": "score", "description": "评分没有考虑我的正确排查步骤"}
        self.assertEqual(self.client.post(path, json=body, headers=self._headers(self.alice)).status_code, 404)
        self.assertEqual(self.client.post(path, json={**body, "question_id": "not-in-report"},
                          headers=self._headers(self.demo)).status_code, 422)
        created = self.client.post(path, json=body, headers=self._headers(self.demo))
        self.assertEqual(created.status_code, 200, created.text)
        feedback_id = created.json()["id"]
        self.assertEqual(created.json()["original_snapshot"]["grade"]["total_score"], 2)
        self.assertFalse(any(item["id"] == feedback_id for item in
                             self.client.get(path, headers=self._headers(self.alice)).json()["items"]))
        review_path = f"{path}/{feedback_id}/review"
        review = {"status": "accepted", "review_note": "经核对原答案，用户指出的问题成立，需要修改规则"}
        self.assertEqual(self.client.put(review_path, json=review,
                          headers=self._headers(self.demo)).status_code, 403)
        self.assertEqual(self.client.put(review_path, json=review,
                          headers=self._headers(self.admin)).status_code, 200)
        with SessionLocal() as db:
            self.assertEqual(db.get(Assessment, assessment_id).overall_avg, 2.0)

    def test_training_assignment_requires_enrollment_and_matching_new_evidence(self) -> None:
        payload = {"user_id": self.demo["user_id"], "profile_id": "big_data", "service_id": "glue",
                   "kind": "assessment", "capability_id": "", "question_count": 6,
                   "difficulty_profile": "foundation", "note": "完成本周 Glue 网络专项训练"}
        path = "/api/assignments"
        self.assertEqual(self.client.post(path, json=payload,
                         headers=self._headers(self.demo)).status_code, 403)
        with SessionLocal() as db:
            if not db.query(TrainingEnrollment).filter_by(user_id=self.demo["user_id"],
                                                          profile_id="big_data").first():
                db.add(TrainingEnrollment(user_id=self.demo["user_id"], profile_id="big_data"))
                db.commit()
        created = self.client.post(path, json=payload, headers=self._headers(self.admin))
        self.assertEqual(created.status_code, 201, created.text)
        assignment_id = created.json()["id"]
        self.assertEqual(created.json()["status"], "pending")
        self.assertEqual(self.client.post(path, json=payload,
                         headers=self._headers(self.admin)).status_code, 409)
        self.assertIn(assignment_id, {item["id"] for item in self.client.get(path,
            headers=self._headers(self.demo)).json()["items"]})
        session_id, assessment_id = uuid.uuid4().hex, uuid.uuid4().hex
        with SessionLocal() as db:
            db.add(QuestionSession(id=session_id, user_id=self.demo["user_id"], profile_id="big_data",
                service_id="glue", questions=[], blueprint={"difficulty_profile": "foundation",
                "focus": "architecture", "scope": "comprehensive",
                "capability_ids": ["glue_network"]}))
            db.add(Assessment(id=assessment_id, session_id=session_id, user_id=self.demo["user_id"],
                profile_id="big_data", service_id="glue", kind="pre", record_origin="user",
                questions_snapshot=[{"id": f"q{i}"} for i in range(6)],
                question_results=[{"type": "open", "scoring_version": "assessment_v2"}]))
            db.commit()
        self.assertEqual(next(item for item in self.client.get(path,
            headers=self._headers(self.demo)).json()["items"] if item["id"] == assignment_id)["status"], "pending")
        with SessionLocal() as db:
            db.get(QuestionSession, session_id).blueprint = {"difficulty_profile": "foundation",
                "focus": "comprehensive", "scope": "comprehensive", "capability_ids": ["glue_network"]}
            db.commit()
        self.assertEqual(next(item for item in self.client.get(path,
            headers=self._headers(self.demo)).json()["items"] if item["id"] == assignment_id)["status"], "pending")
        with SessionLocal() as db:
            db.get(Assessment, assessment_id).question_results = [
                {"type": "open", "scoring_version": "assessment_v3"}]
            db.commit()
        row = next(item for item in self.client.get(path, headers=self._headers(self.demo)).json()["items"]
                   if item["id"] == assignment_id)
        self.assertEqual((row["status"], row["evidence_id"]), ("completed", assessment_id))

    def test_operation_metrics_are_manager_only_and_use_observed_usage(self) -> None:
        task_id = uuid.uuid4().hex
        with SessionLocal() as db:
            db.add(BackgroundTask(id=task_id, user_id=self.demo["user_id"], profile_id="big_data",
                                  status="done", job_kind="generate", runtime_ms=1200,
                                  llm_usage=[{"model": "test-model", "status": "ok", "elapsed_ms": 1000,
                                              "prompt_tokens": 200, "completion_tokens": 100}]))
            db.commit()
        path = "/api/admin/operations?profile_id=big_data&days=30"
        self.assertEqual(self.client.get(path, headers=self._headers(self.demo)).status_code, 403)
        with patch.dict(os.environ, {"SAGE_LLM_PRICES_JSON": json.dumps({
                "test-model": {"input_per_million": 1.0, "output_per_million": 2.0}})}):
            response = self.client.get(path, headers=self._headers(self.admin))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["by_model"]["test-model"]["prompt_tokens"], 200)
        self.assertAlmostEqual(response.json()["estimated_usd"], 0.0004)
        self.assertTrue(any(item["kind"] == "generate" and item["p50_ms"] is not None
                            for item in response.json()["by_kind"]))
        with SessionLocal() as db:
            db.get(BackgroundTask, task_id).llm_usage = [
                {"model": "test-model", "status": "ok", "prompt_tokens": 200, "completion_tokens": 100},
                {"model": "test-model", "status": "ok", "prompt_tokens": None, "completion_tokens": None}]
            db.commit()
        with patch.dict(os.environ, {"SAGE_LLM_PRICES_JSON": json.dumps({
                "test-model": {"input_per_million": 1.0, "output_per_million": 2.0}})}):
            missing_usage = self.client.get(path, headers=self._headers(self.admin))
        self.assertIsNone(missing_usage.json()["estimated_usd"])

    def test_history_filters_are_applied_before_pagination(self) -> None:
        assessment_id = uuid.uuid4().hex
        with SessionLocal() as db:
            db.add(Assessment(id=assessment_id, user_id=self.demo["user_id"], profile_id="big_data",
                              service_id="glue", kind="pre", record_origin="user",
                              questions_snapshot=[], question_results=[]))
            db.commit()
        path = f"/api/assessment/archive/{self.demo['user_id']}?category=assessments&limit=1"
        result = self.client.get(path + f"&service_id=glue&state=pre&q={assessment_id}",
                                 headers=self._headers(self.demo))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["total"], 1)
        self.assertEqual(result.json()["items"][0]["assessment_id"], assessment_id)
        self.assertEqual(self.client.get(path + f"&service_id=athena&q={assessment_id}",
                         headers=self._headers(self.demo)).json()["total"], 0)

    def test_rag_limits_candidates_and_filters_capability(self) -> None:
        retriever = KnowledgeRetriever.__new__(KnowledgeRetriever)
        retriever._collection = MagicMock()
        retriever._collection.count.return_value = 100
        retriever._embed = lambda _: [[0.0] * 256]
        retriever._settings = SimpleNamespace(rag_retrieve_k=12, rag_rerank_k=5)
        retriever._semantic_embeddings = False
        retriever._reranker = None
        docs = (
            KnowledgeDocument("wanted", "Glue network", "official_doc", "Glue network",
                              "glue", "glue_network"),
            KnowledgeDocument("other-cap", "Glue network", "official_doc", "Glue network",
                              "glue", "glue_catalog"),
            KnowledgeDocument("other-service", "Glue network", "official_doc", "Glue network",
                              "athena", "glue_network"),
        )
        with patch("app.services.rag.load_knowledge_documents", return_value=docs):
            results = retriever.search(query="Glue network", service_id="glue",
                                       capability_ids=["glue_network"], limit=5)
        self.assertEqual([item.document.document_id for item in results], ["wanted"])
        retriever._collection.query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
