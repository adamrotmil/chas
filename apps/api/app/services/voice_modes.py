from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from sqlmodel import Session, select

from app.models import VoiceMode, utcnow


DEFAULT_SYSTEM_PROMPT = "You are Charles Rotmil. Write naturally in his voice."

DEFAULT_VOICE_MODES: List[Dict[str, str]] = [
    {"slug": "father_to_adam", "label": "Father to Adam"},
    {"slug": "casual_email", "label": "Casual Email"},
    {"slug": "memoir_scene", "label": "Memoir Scene"},
    {"slug": "argument", "label": "Argument"},
    {"slug": "comic_observation", "label": "Comic Observation"},
    {"slug": "grief_memory", "label": "Grief Memory"},
    {"slug": "photography_reflection", "label": "Photography Reflection"},
    {"slug": "philosophical_fragment", "label": "Philosophical Fragment"},
    {"slug": "spoken_interview", "label": "Spoken Interview"},
    {"slug": "logistical_note", "label": "Logistical Note"},
    {"slug": "verbatim_email_reply", "label": "Verbatim Email Reply"},
    {"slug": "adam_prompted_memory", "label": "Adam Prompted Memory"},
    {"slug": "source_based_story_recall", "label": "Source Based Story Recall"},
    {"slug": "mundane_text_message", "label": "Mundane Text Message"},
    {"slug": "ps_digression", "label": "P.S. Digression"},
    {"slug": "nb_digression", "label": "N.B. Digression"},
    {"slug": "long_literary_source_excerpt", "label": "Long Literary Source Excerpt"},
    {"slug": "multi_turn_thread", "label": "Multi-turn Thread"},
    {"slug": "first_person_recollection", "label": "First Person Recollection"},
]


def slugify_voice_mode(label_or_slug: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", label_or_slug.strip().lower()).strip("_")
    return cleaned or "custom_voice_mode"


def ensure_default_voice_modes(session: Session) -> None:
    existing = {mode.slug for mode in session.exec(select(VoiceMode)).all()}
    for item in DEFAULT_VOICE_MODES:
        if item["slug"] in existing:
            continue
        session.add(
            VoiceMode(
                slug=item["slug"],
                label=item["label"],
                default_system_prompt=DEFAULT_SYSTEM_PROMPT,
                family="imported_examples",
                status="active",
                created_by="system_default",
            )
        )
    session.flush()


def list_voice_modes(session: Session) -> List[VoiceMode]:
    ensure_default_voice_modes(session)
    return session.exec(
        select(VoiceMode).where(VoiceMode.status == "active").order_by(VoiceMode.label.asc())
    ).all()


def find_voice_mode(session: Session, slug: Optional[str]) -> Optional[VoiceMode]:
    if not slug:
        return None
    ensure_default_voice_modes(session)
    return session.exec(select(VoiceMode).where(VoiceMode.slug == slug)).first()


def upsert_voice_mode(
    session: Session,
    *,
    label: str,
    slug: Optional[str] = None,
    description: Optional[str] = None,
    default_system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    family: Optional[str] = None,
    status: str = "active",
    metadata_json: Optional[Dict[str, Any]] = None,
    created_by: str = "adam",
) -> VoiceMode:
    ensure_default_voice_modes(session)
    mode_slug = slugify_voice_mode(slug or label)
    mode = session.exec(select(VoiceMode).where(VoiceMode.slug == mode_slug)).first()
    if mode is None:
        mode = VoiceMode(slug=mode_slug, label=label.strip() or mode_slug, created_by=created_by)
    mode.label = label.strip() or mode.label
    mode.description = description
    mode.default_system_prompt = default_system_prompt or DEFAULT_SYSTEM_PROMPT
    mode.family = family
    mode.status = status or "active"
    mode.metadata_json = metadata_json or {}
    mode.updated_at = utcnow()
    session.add(mode)
    session.flush()
    return mode
