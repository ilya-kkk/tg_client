import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app import main
from app.models import WarmupJobCreate


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
