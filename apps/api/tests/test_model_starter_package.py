import io
import hashlib
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
from app.models import ContextPack, DPOPair, GoldVoiceExample, SFTCandidate


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


def test_model_starter_export_can_include_precomputed_split_files():
    client, _engine = build_client()

    response = client.get("/api/model-starter/export.zip", params={"include_split": True, "val_ratio": 0.5, "seed": 42})
    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "charles-model/data/charles_sft.train.jsonl" in names
        assert "charles-model/data/charles_sft.val.jsonl" in names
        train_rows = _jsonl_rows(archive.read("charles-model/data/charles_sft.train.jsonl").decode("utf-8"))
        val_rows = _jsonl_rows(archive.read("charles-model/data/charles_sft.val.jsonl").decode("utf-8"))
        source_rows = _jsonl_rows(archive.read("charles-model/data/charles_sft.jsonl").decode("utf-8"))
        assert len(train_rows) == 1
        assert len(val_rows) == 1
        assert {row["id"] for row in train_rows + val_rows} == {row["id"] for row in source_rows}


def test_model_starter_preview_matches_exported_package_contents():
    client, _engine = build_client()

    preview = client.get("/api/model-starter/preview")
    assert preview.status_code == 200
    body = preview.json()
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
    assert body["sft_jsonl"].endswith("\n")
    assert body["dpo_jsonl"].endswith("\n")
    summaries = {item["path"]: item for item in body["file_summaries"]}

    export = client.get("/api/model-starter/export.zip")
    assert export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        for path in body["package_tree"]:
            content = archive.read(path)
            assert summaries[path]["byte_count"] == len(content)
            assert summaries[path]["sha256"] == hashlib.sha256(content).hexdigest()
        assert archive.read("charles-model/data/charles_sft.jsonl").decode("utf-8") == body["sft_jsonl"]
        assert archive.read("charles-model/data/charles_dpo.jsonl").decode("utf-8") == body["dpo_jsonl"]
        assert archive.read("charles-model/configs/train_sft.yaml").decode("utf-8") == body["train_config"]


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
    assert third.status_code == 200


def test_model_starter_imports_approved_workbench_exports_once():
    client, engine = build_client()
    with Session(engine) as session:
        context = ContextPack(
            human_id="CTX_MODEL_STARTER_IMPORT",
            user_intent="gold_voice_generation",
            requested_voice_mode="father_to_adam",
            truth_mode="adam_expert_reconstruction",
            boundaries_snapshot={"boundary_status": "passed"},
        )
        session.add(context)
        session.flush()
        sft_gold = GoldVoiceExample(
            human_id="GOLD_MODEL_STARTER_IMPORT_SFT",
            context_pack_id=context.id,
            voice_mode="father_to_adam",
            truth_status="adam_expert_reconstruction",
            adam_gold_edit="walked early for the bread.\nsmall good thing.\n\nlove\ndad",
            downstream_use={"sft": True, "artifact_mode": "sft", "context": "approved import fixture"},
            ratings={"response_rubric": {"response_b": {"privacy_export_safety": {"status": "no_issues"}}}},
        )
        session.add(sft_gold)
        session.flush()
        session.add(
            SFTCandidate(
                source_gold_voice_example_id=sft_gold.id,
                messages=[
                    {"role": "system", "content": "You are Charles Rotmil."},
                    {"role": "user", "content": "Tell Adam about Sunday bread."},
                    {"role": "assistant", "content": sft_gold.adam_gold_edit},
                ],
                export_status="approved",
            )
        )
        dpo_gold = GoldVoiceExample(
            human_id="GOLD_MODEL_STARTER_IMPORT_DPO",
            context_pack_id=context.id,
            voice_mode="father_to_adam",
            truth_status="adam_expert_reconstruction",
            adam_gold_edit="coffee was strong...\nblack.\ncorrect.\n\nlove\ndad",
            downstream_use={"dpo": True, "artifact_mode": "dpo", "context": "approved dpo import fixture"},
            ratings={"response_rubric": {"response_b": {"privacy_export_safety": {"status": "no_issues"}}}},
        )
        session.add(dpo_gold)
        session.flush()
        session.add(
            DPOPair(
                source_gold_voice_example_id=dpo_gold.id,
                prompt="How was the coffee?",
                chosen=dpo_gold.adam_gold_edit,
                rejected="The coffee was strong and black, which was appropriate.",
                reason=["chosen keeps Charles cadence; rejected is generic"],
                export_status="approved",
            )
        )
        session.commit()

    imported = client.post("/api/model-starter/import-approved")
    assert imported.status_code == 200
    body = imported.json()
    assert body["imported_sft_count"] == 1
    assert body["imported_dpo_count"] == 1
    assert body["skipped_existing_count"] == 0

    sft_rows = client.get("/api/model-starter/sft").json()
    dpo_rows = client.get("/api/model-starter/dpo").json()
    assert any(row["instruction"] == "Tell Adam about Sunday bread." for row in sft_rows)
    assert any(row["prompt"] == "How was the coffee?" for row in dpo_rows)

    second = client.post("/api/model-starter/import-approved")
    assert second.status_code == 200
    assert second.json()["imported_sft_count"] == 0
    assert second.json()["imported_dpo_count"] == 0
    assert second.json()["skipped_existing_count"] == 2
