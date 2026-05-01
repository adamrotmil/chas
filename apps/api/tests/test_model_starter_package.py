import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app


def build_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    app.dependency_overrides.clear()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine


def _jsonl_rows(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_model_starter_seeds_valid_training_rows_and_allows_crud():
    client, _engine = build_client()

    summary = client.get("/api/model-starter/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["sft_count"] == 2
    assert body["dpo_count"] == 2
    assert body["validation"]["ready"] is True
    assert body["package_tree"] == [
        "charles-model/data/charles_sft.jsonl",
        "charles-model/data/charles_dpo.jsonl",
        "charles-model/data/README.md",
        "charles-model/configs/train_sft.yaml",
        "charles-model/scripts/check_jsonl.py",
        "charles-model/scripts/split_canary_val.py",
        "charles-model/.gitignore",
    ]

    created = client.post(
        "/api/model-starter/sft",
        json={
            "id": "sft-003",
            "instruction": "Tell Adam about Sunday bread.",
            "response": "walked early for the bread.\nstill warm when I got back.\nsmall thing but good.\n\nlove\ndad",
            "voice": "father_to_adam",
            "tone": "ordinary_intimate",
            "provenance": "test fixture",
            "consent_status": "family_private_training_ok",
            "pii_tags": ["Adam", "Charles"],
            "notes": "Added through API.",
        },
    )
    assert created.status_code == 200
    assert created.json()["id"] == "sft-003"

    updated = client.put(
        "/api/model-starter/sft/sft-003",
        json={"tone": "mundane_text_message", "notes": "Edited through API."},
    )
    assert updated.status_code == 200
    assert updated.json()["tone"] == "mundane_text_message"
    assert updated.json()["notes"] == "Edited through API."

    deleted = client.delete("/api/model-starter/sft/sft-003")
    assert deleted.status_code == 200
    ids = [row["id"] for row in client.get("/api/model-starter/sft").json()]
    assert "sft-003" not in ids


def test_model_starter_validation_catches_strict_errors_and_warnings():
    client, _engine = build_client()
    response = client.post(
        "/api/model-starter/dpo",
        json={
            "id": "dpo-bad",
            "prompt": "How was the soup?",
            "chosen": "same response",
            "rejected": "same response",
            "provenance": "test fixture",
            "why_chosen": "",
            "notes": "",
        },
    )
    assert response.status_code == 200

    validation = client.post("/api/model-starter/validate")
    assert validation.status_code == 200
    body = validation.json()
    assert body["ready"] is False
    assert body["error_count"] == 1
    assert body["warning_count"] >= 1
    codes = {issue["code"] for issue in body["issues"]}
    assert "chosen_rejected_identical" in codes
    assert "chosen_unusually_short" in codes


def test_model_starter_export_zip_has_exact_trainer_ready_package_and_scripts(tmp_path: Path):
    client, _engine = build_client()

    response = client.post("/api/model-starter/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        expected = {
            "charles-model/data/charles_sft.jsonl",
            "charles-model/data/charles_dpo.jsonl",
            "charles-model/data/README.md",
            "charles-model/configs/train_sft.yaml",
            "charles-model/scripts/check_jsonl.py",
            "charles-model/scripts/split_canary_val.py",
            "charles-model/.gitignore",
        }
        assert names == expected
        assert "template: \"instruction-response\"" in archive.read("charles-model/configs/train_sft.yaml").decode("utf-8")
        sft = archive.read("charles-model/data/charles_sft.jsonl").decode("utf-8")
        dpo = archive.read("charles-model/data/charles_dpo.jsonl").decode("utf-8")
        assert len(_jsonl_rows(sft)) == 2
        assert len(_jsonl_rows(dpo)) == 2
        for row in _jsonl_rows(sft):
            assert {"id", "instruction", "response", "voice", "tone", "provenance", "consent_status", "pii_tags"}.issubset(row)
        for row in _jsonl_rows(dpo):
            assert {"id", "prompt", "chosen", "rejected", "provenance", "why_chosen"}.issubset(row)
        archive.extractall(tmp_path)

    package = tmp_path / "charles-model"
    check = subprocess.run(
        [sys.executable, str(package / "scripts/check_jsonl.py"), str(package / "data/charles_sft.jsonl"), "--type", "sft"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert "errors=0" in check.stdout

    split = subprocess.run(
        [sys.executable, str(package / "scripts/split_canary_val.py"), str(package / "data/charles_sft.jsonl"), "--val-ratio", "0.5", "--seed", "42"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert split.returncode == 0, split.stdout + split.stderr
    assert (package / "data/charles_sft.train.jsonl").exists()
    assert (package / "data/charles_sft.val.jsonl").exists()


def test_model_starter_split_is_deterministic():
    client, _engine = build_client()
    first = client.post("/api/model-starter/split", json={"val_ratio": 0.5, "seed": 17})
    second = client.post("/api/model-starter/split", json={"val_ratio": 0.5, "seed": 17})
    third = client.post("/api/model-starter/split", json={"val_ratio": 0.5, "seed": 18})
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert first.json() == second.json()
    assert first.json()["source_count"] == 2
    assert first.json()["train_count"] == 1
    assert first.json()["val_count"] == 1
    assert first.json()["val_ids"] != third.json()["val_ids"]
