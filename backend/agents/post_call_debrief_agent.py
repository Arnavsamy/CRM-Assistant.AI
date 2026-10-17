"""Post-call notes analysis for the lightweight agent demo."""

import json
import logging
from typing import Any, Dict

from backend.database import db
from backend.factory import get_chat_model

logger = logging.getLogger("post_call_debrief_agent")

ALLOWED_STAGES = {"New", "Contacted", "Replied", "Meeting", "Evaluation", "Proposal", "Won", "Lost", "Draft Ready"}


def _clean_json(text: str) -> str:
    text = str(text).strip()
    if "```json" in text:
        text = text.split("```json", 1)[1]
    if "```" in text:
        text = text.split("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start >= 0 and end > start else text


def _fallback(stage: str, reason: str) -> Dict[str, Any]:
    return {
        "summary": "The notes could not be analyzed reliably.",
        "proposed_stage": stage,
        "stage_confidence": 0,
        "stakeholders": [],
        "objections": [reason],
        "contradictions": [],
        "next_action": {"title": "Review the call notes manually", "description": reason, "priority": "low"},
    }


async def analyze_post_call_debrief(lead_id: str, notes: str) -> Dict[str, Any]:
    lead = await db.get_lead_with_company(lead_id)
    if not lead:
        raise ValueError("Lead not found")
    events = await db.get_lead_events(lead_id)
    company = lead.get("company") or {}
    existing = "\n".join(f"[{item['event_type']}] {item['content']}" for item in events[:20]) or "No previous activity recorded."
    prompt = f"""
You are a careful B2B post-call debrief analyst. Do not invent facts. Use only evidence in the notes and previous activity.
Return ONLY valid JSON with this structure:
{{
  "summary": "short factual summary",
  "proposed_stage": "New|Contacted|Replied|Meeting|Evaluation|Proposal|Won|Lost|Draft Ready",
  "stage_confidence": 0,
  "stakeholders": [{{"name": "person or unknown", "role": "role", "evidence": "short evidence"}}],
  "objections": ["short objection"],
  "contradictions": [{{"previous": "existing fact", "new": "new statement", "evidence": "why this conflicts"}}],
  "next_action": {{"title": "one concrete next action", "description": "why", "priority": "high|medium|low"}}
}}

Company: {company.get('name', '')}
Current stage: {lead.get('status') or 'New'}
Previous activity:
{existing}

New call notes:
{notes}
"""
    try:
        response = await get_chat_model(temperature=0.0).ainvoke(prompt)
        result = json.loads(_clean_json(response.content))
        current = lead.get("status") or "New"
        stage = str(result.get("proposed_stage", current))
        if stage not in ALLOWED_STAGES:
            stage = current
        action = result.get("next_action") or {}
        priority = str(action.get("priority", "medium")).lower()
        if priority not in {"high", "medium", "low"}:
            priority = "medium"
        return {
            "summary": str(result.get("summary", "")),
            "proposed_stage": stage,
            "stage_confidence": max(0, min(100, int(result.get("stage_confidence", 0)))),
            "stakeholders": result.get("stakeholders", []),
            "objections": result.get("objections", []),
            "contradictions": result.get("contradictions", []),
            "next_action": {"title": str(action.get("title", "Review call outcome")), "description": str(action.get("description", "")), "priority": priority},
        }
    except Exception as exc:
        logger.exception("Post-call debrief failed: %s", exc)
        return _fallback(lead.get("status") or "New", "AI analysis was unavailable; verify the notes manually.")


async def apply_post_call_debrief(workspace_id: str, lead_id: str, notes: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    lead = await db.get_lead_with_company(lead_id)
    if not lead:
        raise ValueError("Lead not found")
    current = lead.get("status") or "New"
    proposed = str(analysis.get("proposed_stage") or current)
    if proposed in ALLOWED_STAGES and proposed != current:
        await db.update_lead_status(lead_id, proposed)
    action = analysis.get("next_action") or {}
    task = await db.create_task(
        workspace_id=workspace_id,
        lead_id=lead_id,
        title=str(action.get("title") or "Review post-call follow-up"),
        description=str(action.get("description") or "Review the approved post-call debrief."),
        priority=str(action.get("priority") or "medium"),
        source="post_call_debrief",
    )
    await db.create_lead_event(
        lead_id=lead_id,
        event_type="post_call_debrief",
        content=str(analysis.get("summary") or "Post-call debrief applied."),
        source="post_call_debrief",
        metadata={"notes": notes, "analysis": analysis, "task_id": task["id"]},
    )
    return {"status": "applied", "stage": proposed, "task": task, "analysis": analysis}
