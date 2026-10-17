import json
import logging
from typing import Any, Dict, List

from backend.database import db
from backend.factory import get_chat_model

logger = logging.getLogger("lead_intelligence_agent")


ALLOWED_STAGES = {
    "New",
    "Contacted",
    "Replied",
    "Meeting",
    "Evaluation",
    "Proposal",
    "Won",
    "Lost",
    "Draft Ready"
}


def clean_json(text: str) -> str:
    """Extracts the first JSON object from an LLM response."""
    text = str(text).strip()

    if "```json" in text:
        text = text.split("```json", 1)[1]

    if "```" in text:
        text = text.split("```", 1)[0]

    start = text.find("{")
    end = text.rfind("}")

    return text[start:end + 1] if start >= 0 and end > start else text


def safe_analysis(current_stage: str, reason: str) -> Dict[str, Any]:
    return {
        "actual_stage": current_stage,
        "stage_confidence": 20,
        "competitor_signals": [],
        "buyer_intent": "unknown",
        "blockers": [reason],
        "next_action": {
            "title": "Collect the next buyer interaction",
            "description": reason,
            "priority": "low"
        }
    }


async def analyze_lead_intelligence(
    workspace_id: str,
    lead_id: str
) -> Dict[str, Any]:
    """Analyzes lead activity and creates one recommended follow-up task."""
    lead = await db.get_lead_with_company(lead_id)
    if not lead:
        raise ValueError("Lead not found")

    events = await db.get_lead_events(lead_id)
    current_stage = lead.get("status") or "New"

    if not events:
        analysis = safe_analysis(
            current_stage,
            "No email, call, meeting, or CRM activity has been recorded yet."
        )
    else:
        company = lead.get("company") or {}
        event_context = "\n".join(
            f"[{event['event_type']}] {event['content']}"
            for event in events[:20]
        )

        prompt = f"""
You are a careful B2B sales intelligence analyst.

Analyze the lead activity below. Do not invent facts. Treat competitor
mentions as signals only when the evidence explicitly supports them.

Return ONLY valid JSON with this exact structure:
{{
  "actual_stage": "New|Contacted|Replied|Meeting|Evaluation|Proposal|Won|Lost|Draft Ready",
  "stage_confidence": 0,
  "competitor_signals": [
    {{"name": "competitor or unknown", "evidence": "exact short evidence", "confidence": 0}}
  ],
  "buyer_intent": "high|medium|low|unknown",
  "blockers": ["short blocker"],
  "next_action": {{
    "title": "one concrete action",
    "description": "why this action is appropriate",
    "priority": "high|medium|low"
  }}
}}

Current representative stage: {current_stage}
Company: {company.get('name', '')}
Industry: {company.get('industry', '')}

Lead activity:
{event_context}
"""

        try:
            response = await get_chat_model(temperature=0.0).ainvoke(prompt)
            parsed = json.loads(clean_json(response.content))

            actual_stage = str(parsed.get("actual_stage", current_stage))
            if actual_stage not in ALLOWED_STAGES:
                actual_stage = current_stage

            analysis = {
                "actual_stage": actual_stage,
                "stage_confidence": max(0, min(100, int(parsed.get("stage_confidence", 50)))),
                "competitor_signals": parsed.get("competitor_signals", []),
                "buyer_intent": str(parsed.get("buyer_intent", "unknown")),
                "blockers": parsed.get("blockers", []),
                "next_action": parsed.get("next_action", {})
            }
        except Exception as exc:
            logger.exception("Lead intelligence analysis failed: %s", exc)
            analysis = safe_analysis(
                current_stage,
                "The activity could not be analyzed reliably. Review it manually."
            )

    next_action = analysis.get("next_action") or {}
    title = str(next_action.get("title", "Review lead activity"))
    description = str(next_action.get("description", "Review the latest lead signals."))
    priority = str(next_action.get("priority", "medium")).lower()
    if priority not in {"high", "medium", "low"}:
        priority = "medium"

    task = await db.create_task(
        workspace_id=workspace_id,
        lead_id=lead_id,
        title=title,
        description=description,
        priority=priority,
        source="lead_intelligence"
    )

    await db.create_lead_event(
        lead_id=lead_id,
        event_type="ai_analysis",
        content=json.dumps(analysis),
        source="lead_intelligence",
        metadata={"task_id": task["id"]}
    )

    return {
        "lead_id": lead_id,
        "current_stage": current_stage,
        "analysis": analysis,
        "task": task
    }
