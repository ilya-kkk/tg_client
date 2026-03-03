import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app import main


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
