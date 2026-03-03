import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app import main
from app.models import WarmupJobCreate, WarmupJobUpdate


class StubWarmupJobsRepo:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.received_user_id: str | None = None

    def list_by_user(self, user_id: str) -> list[dict]:
        self.received_user_id = user_id
        return self.rows


class FailingWarmupJobsRepo:
    def list_by_user(self, user_id: str) -> list[dict]:
        raise RuntimeError("repo failure")


class StubWarmupJobsCreateRepo:
    def __init__(self):
        self.received_user_id: str | None = None
        self.received_payload: dict | None = None

    def create(self, user_id: str, payload: dict) -> dict:
        self.received_user_id = user_id
        self.received_payload = payload
        now = datetime.now(timezone.utc)
        return {
            "id": "job-2",
            "user_id": user_id,
            "name": payload["name"],
            "account_sessions": payload["account_sessions"],
            "mode": payload["mode"],
            "actions_per_day": payload["actions_per_day"],
            "enabled_actions": payload["enabled_actions"],
            "target_channels": payload["target_channels"],
            "is_active": payload["is_active"],
            "created_at": now,
            "updated_at": now,
        }


class FailingWarmupJobsCreateRepo:
    def create(self, user_id: str, payload: dict) -> dict:
        raise RuntimeError("create failure")


class StubWarmupJobsUpdateRepo:
    def __init__(self, row_to_return: dict | None):
        self.row_to_return = row_to_return
        self.received_user_id: str | None = None
        self.received_job_id: str | None = None
        self.received_payload: dict | None = None

    def update(self, user_id: str, job_id: str, payload: dict) -> dict | None:
        self.received_user_id = user_id
        self.received_job_id = job_id
        self.received_payload = payload
        return self.row_to_return


class FailingWarmupJobsUpdateRepo:
    def update(self, user_id: str, job_id: str, payload: dict) -> dict:
        raise RuntimeError("update failure")


def test_list_warmup_jobs_returns_rows(monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    repo = StubWarmupJobsRepo(
        rows=[
            {
                "id": "job-1",
                "user_id": "user-1",
                "name": "Morning warmup",
                "account_sessions": ["session-a"],
                "mode": "normal",
                "actions_per_day": 35,
                "enabled_actions": ["read_messages", "react_to_message"],
                "target_channels": ["@channel_a"],
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        ]
    )
    monkeypatch.setattr(main, "warmup_jobs_repo", repo)

    result = asyncio.run(main.list_warmup_jobs("user-1"))

    assert repo.received_user_id == "user-1"
    assert len(result) == 1
    assert result[0].id == "job-1"
    assert result[0].mode == "normal"
    assert result[0].actions_per_day == 35


def test_list_warmup_jobs_returns_503_when_repo_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "warmup_jobs_repo", None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.list_warmup_jobs("user-1"))

    assert exc.value.status_code == 503


def test_list_warmup_jobs_returns_500_on_repo_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "warmup_jobs_repo", FailingWarmupJobsRepo())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.list_warmup_jobs("user-1"))

    assert exc.value.status_code == 500
    assert "repo failure" in exc.value.detail


def test_create_warmup_job_sets_actions_per_day_from_mode(monkeypatch: pytest.MonkeyPatch):
    repo = StubWarmupJobsCreateRepo()
    monkeypatch.setattr(main, "warmup_jobs_repo", repo)
    request = WarmupJobCreate(
        name="Night warmup",
        account_sessions=["session-a", "session-b"],
        mode="aggressive",
        enabled_actions=["read_messages", "react_to_message"],
        target_channels=["@channel_a", "@channel_b"],
    )

    result = asyncio.run(main.create_warmup_job("user-1", request))

    assert repo.received_user_id == "user-1"
    assert repo.received_payload is not None
    assert repo.received_payload["actions_per_day"] == 90
    assert repo.received_payload["is_active"] is False
    assert result.id == "job-2"
    assert result.mode == "aggressive"
    assert result.actions_per_day == 90
    assert result.is_active is False


def test_create_warmup_job_returns_503_when_repo_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "warmup_jobs_repo", None)
    request = WarmupJobCreate(
        name="Night warmup",
        account_sessions=["session-a"],
        mode="normal",
        enabled_actions=["read_messages"],
        target_channels=["@channel_a"],
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.create_warmup_job("user-1", request))

    assert exc.value.status_code == 503


def test_create_warmup_job_returns_500_on_repo_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "warmup_jobs_repo", FailingWarmupJobsCreateRepo())
    request = WarmupJobCreate(
        name="Night warmup",
        account_sessions=["session-a"],
        mode="normal",
        enabled_actions=["read_messages"],
        target_channels=["@channel_a"],
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.create_warmup_job("user-1", request))

    assert exc.value.status_code == 500
    assert "create failure" in exc.value.detail


def test_update_warmup_job_updates_mode_and_recalculates_actions_per_day(monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    repo = StubWarmupJobsUpdateRepo(
        row_to_return={
            "id": "job-1",
            "user_id": "user-1",
            "name": "Night warmup v2",
            "account_sessions": ["session-a"],
            "mode": "normal",
            "actions_per_day": 35,
            "enabled_actions": ["read_messages"],
            "target_channels": ["@channel_a"],
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
    )
    monkeypatch.setattr(main, "warmup_jobs_repo", repo)
    request = WarmupJobUpdate(name="Night warmup v2", mode="normal")

    result = asyncio.run(main.update_warmup_job("user-1", "job-1", request))

    assert repo.received_user_id == "user-1"
    assert repo.received_job_id == "job-1"
    assert repo.received_payload is not None
    assert repo.received_payload["name"] == "Night warmup v2"
    assert repo.received_payload["mode"] == "normal"
    assert repo.received_payload["actions_per_day"] == 35
    assert result.mode == "normal"
    assert result.actions_per_day == 35


def test_update_warmup_job_toggles_is_active(monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    repo = StubWarmupJobsUpdateRepo(
        row_to_return={
            "id": "job-1",
            "user_id": "user-1",
            "name": "Night warmup",
            "account_sessions": ["session-a"],
            "mode": "normal",
            "actions_per_day": 35,
            "enabled_actions": ["read_messages"],
            "target_channels": ["@channel_a"],
            "is_active": False,
            "created_at": now,
            "updated_at": now,
        }
    )
    monkeypatch.setattr(main, "warmup_jobs_repo", repo)

    result = asyncio.run(main.update_warmup_job("user-1", "job-1", WarmupJobUpdate(is_active=False)))

    assert repo.received_payload == {"is_active": False}
    assert result.is_active is False


def test_update_warmup_job_returns_400_when_payload_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "warmup_jobs_repo", StubWarmupJobsUpdateRepo(row_to_return=None))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.update_warmup_job("user-1", "job-1", WarmupJobUpdate()))

    assert exc.value.status_code == 400


def test_update_warmup_job_returns_404_when_job_not_found(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "warmup_jobs_repo", StubWarmupJobsUpdateRepo(row_to_return=None))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            main.update_warmup_job(
                "user-1",
                "job-unknown",
                WarmupJobUpdate(is_active=True),
            )
        )

    assert exc.value.status_code == 404


def test_update_warmup_job_returns_503_when_repo_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "warmup_jobs_repo", None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.update_warmup_job("user-1", "job-1", WarmupJobUpdate(is_active=True)))

    assert exc.value.status_code == 503


def test_update_warmup_job_returns_500_on_repo_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "warmup_jobs_repo", FailingWarmupJobsUpdateRepo())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.update_warmup_job("user-1", "job-1", WarmupJobUpdate(is_active=True)))

    assert exc.value.status_code == 500
    assert "update failure" in exc.value.detail
