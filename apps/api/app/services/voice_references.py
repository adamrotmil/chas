from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import EmbeddingRecord, Segment, VoiceReferenceExample, utcnow
from app.services.embeddings import upsert_embedding_record


ROLES = {"system", "user", "assistant"}


def _count(session: Session) -> int:
    return len(session.exec(select(VoiceReferenceExample)).all()) + 1


def _string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def parse_formatted_prompt_pair(text: str) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    current_role: Optional[str] = None
    current_lines: List[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        lowered = line[:-1].lower() if line.endswith(":") else ""
        if lowered in ROLES:
            if current_role:
                messages.append({"role": current_role, "content": "\n".join(current_lines).strip()})
            current_role = lowered
            current_lines = []
            continue
        if current_role:
            current_lines.append(raw_line)
    if current_role:
        messages.append({"role": current_role, "content": "\n".join(current_lines).strip()})
    return [message for message in messages if message["content"]]


def _messages_from_chunk(chunk: Segment) -> List[Dict[str, str]]:
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    structured = metadata.get("messages") or metadata.get("structured_messages")
    if isinstance(structured, list):
        messages = []
        for message in structured:
            if not isinstance(message, dict):
                continue
            role = _string(message.get("role"))
            content = _string(message.get("content"))
            if role in ROLES and content:
                messages.append({"role": role, "content": content})
        if messages:
            return messages
    return parse_formatted_prompt_pair(chunk.text_content or "")


def _first(messages: List[Dict[str, str]], role: str) -> str:
    return next((message["content"] for message in messages if message["role"] == role), "")


def _conversation_family(user_prompt: str, assistant_response: str, messages: List[Dict[str, str]]) -> str:
    user_lower = user_prompt.lower()
    assistant_lower = assistant_response.lower()
    if sum(1 for message in messages if message["role"] == "user") > 1:
        return "multi_turn_thread"
    if "n.b." in assistant_lower or "\nnb" in assistant_lower:
        return "nb_digression"
    if "p.s." in assistant_lower or "\nps" in assistant_lower:
        return "ps_digression"
    if user_lower.startswith(("cathryn:", "tom ", "ruth:", "liz ", "agnès", "agnes", "jack:", "colette:")):
        return "verbatim_email_reply"
    if "tell me about" in user_lower or "what do you remember" in user_lower:
        return "source_based_story_recall"
    if len(assistant_response) < 280:
        return "mundane_text_message"
    return "adam_prompted_memory"


def _voice_mode(user_prompt: str, assistant_response: str, family: str) -> str:
    user_lower = user_prompt.lower()
    assistant_lower = assistant_response.lower()
    if family == "verbatim_email_reply":
        return "casual_email"
    if "photo" in user_lower or "photograph" in user_lower or "camera" in assistant_lower:
        return "photography_reflection"
    if "chess" in assistant_lower or "airport" in user_lower or "what should" in user_lower:
        return "logistical_note"
    if family == "source_based_story_recall":
        return "memoir_scene"
    if "god" in user_lower or "schopenhauer" in user_lower or "diogenes" in user_lower:
        return "philosophical_fragment"
    if "love\ndad" in assistant_lower or assistant_lower.rstrip().endswith("dad"):
        return "father_to_adam"
    return "father_to_adam"


def _tags(messages: List[Dict[str, str]], family: str, voice_mode: str) -> List[str]:
    tags = [family, voice_mode]
    if any("Sent from my iPhone" in message["content"] for message in messages):
        tags.append("iphone_signature")
    if any("love\ndad" in message["content"].lower() for message in messages):
        tags.append("love_dad_closing")
    return list(dict.fromkeys(tags))


def _reference_embedding_text(example: VoiceReferenceExample) -> str:
    return "\n".join(
        [
            f"voice_mode: {example.voice_mode}",
            f"conversation_family: {example.conversation_family}",
            f"user: {example.user_prompt}",
            f"assistant: {example.assistant_response}",
        ]
    )


def upsert_voice_reference_examples_for_chunks(
    *,
    session: Session,
    chunk_ids: List[str],
    annotation_id: str,
    source_task_id: Optional[str] = None,
    source_title: Optional[str] = None,
) -> Dict[str, Any]:
    created_ids: List[str] = []
    embedding_ids: List[str] = []
    chunks = session.exec(select(Segment).where(Segment.id.in_(chunk_ids))).all()
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    for chunk_id in chunk_ids:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
        messages = _messages_from_chunk(chunk)
        user_prompt = _first(messages, "user")
        assistant_response = _first(messages, "assistant")
        if not user_prompt or not assistant_response:
            continue
        system_prompt = _first(messages, "system") or "You are Charles Rotmil."
        family = _conversation_family(user_prompt, assistant_response, messages)
        mode = _voice_mode(user_prompt, assistant_response, family)
        existing = session.exec(
            select(VoiceReferenceExample).where(VoiceReferenceExample.source_segment_id == chunk.id)
        ).first()
        example = existing or VoiceReferenceExample(
            human_id=f"VOICE_REF_{_count(session):06d}",
            source_segment_id=chunk.id,
            source_asset_id=chunk.asset_id,
            user_prompt=user_prompt,
            assistant_response=assistant_response,
        )
        example.source_annotation_id = annotation_id
        example.source_task_id = source_task_id
        example.source_title = source_title or chunk.title
        example.source_chunk_index = _int(chunk.locator.get("chunk_index")) if isinstance(chunk.locator, dict) else None
        example.system_prompt = system_prompt
        example.user_prompt = user_prompt
        example.assistant_response = assistant_response
        example.messages = messages
        example.voice_mode = mode
        example.conversation_family = family
        example.truth_status = chunk.source_truth_status
        example.quality_status = _string(metadata.get("chunk_quality_status"), "reference_ready")
        example.boundary_snapshot = {
            "source_use_mode": metadata.get("source_use_mode"),
            "source_use_modes": metadata.get("source_use_modes", []),
            "quote_policy": metadata.get("quote_policy"),
            "privacy_clearance": metadata.get("privacy_clearance"),
            "pairing_gate": metadata.get("pairing_gate"),
        }
        example.tags = _tags(messages, family, mode)
        example.metadata_json = {
            "prompt_preview": metadata.get("prompt_preview"),
            "response_preview": metadata.get("response_preview"),
            "message_count": len(messages),
            "role_sequence": [message["role"] for message in messages],
            "source_parser": metadata.get("parser"),
            "chunking_strategy": metadata.get("chunking_strategy"),
            "text_extraction_derivative_id": metadata.get("text_extraction_derivative_id"),
        }
        example.status = "active" if example.quality_status in {"pairing_ready_reference", "reference_ready", "reviewed_selected"} else "needs_review"
        example.updated_at = utcnow()
        session.add(example)
        session.flush()
        created_ids.append(example.id)
        embedding = upsert_embedding_record(
            session=session,
            target_type="voice_reference_example",
            target_id=example.id,
            input_text=_reference_embedding_text(example),
            modality="text",
            embedding_type="voice_reference_text",
            model_name="pending_text_embedding",
            truth_status=example.truth_status,
            boundary_snapshot=example.boundary_snapshot,
            metadata={"voice_mode": mode, "conversation_family": family, "source_segment_id": chunk.id},
            created_by="voice_reference_builder",
        )
        if isinstance(embedding, EmbeddingRecord):
            embedding_ids.append(embedding.id)
    return {
        "voice_reference_example_ids": created_ids,
        "voice_reference_embedding_record_ids": embedding_ids,
    }
