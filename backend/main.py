import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, RedirectResponse
from pydantic import BaseModel, Field

from backend.config import settings
from backend.database import db
from backend.agents.product_agent import run_product_pipeline
from backend.agents.rag_service import RAGService
from backend.agents.Chatwok import get as run_chat
from backend.factory import get_chat_model
from backend.Trace1 import RequestTrace

from backend.agents.lead_summary import router as lead_summary_router
from backend.agents.search_chat import router as search_chat_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("main_api")

app = FastAPI(
    title="AI Outreach Assistant API",
    description="AI Revenue Chief of Staff API",
    version="1.2.0"
)

app.include_router(lead_summary_router)
app.include_router(search_chat_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Temporary storage only for accounts, chat messages, and jobs.
# Workspaces and memories are stored through database.py.
WORKSPACE_CACHE: Dict[str, Dict[str, Any]] = {}
JOBS: Dict[str, Dict[str, Any]] = {}


class ProductSubmission(BaseModel):
    product_name: str
    product_description: str
    email: Optional[str] = "user@example.com"


class LeadStatusUpdate(BaseModel):
    status: str


class LeadEventCreate(BaseModel):
    event_type: str
    content: str
    source: str = "manual"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    lead_id: Optional[str] = None
    priority: str = "medium"
    due_at: Optional[datetime] = None
    source: str = "manual"


class WorkspaceCreate(BaseModel):
    company_name: str
    company_description: str
    product_name: Optional[str] = ""
    product_description: Optional[str] = ""
    email: Optional[str] = "user@example.com"


class MemoryCreate(BaseModel):
    fact: str
    category: str = "business"
    approved: bool = False


class AccountCreate(BaseModel):
    name: str
    domain: Optional[str] = ""
    industry: Optional[str] = ""
    description: Optional[str] = ""
    fit_score: int = Field(default=0, ge=0, le=100)
    confidence: int = Field(default=0, ge=0, le=100)
    evidence: List[str] = Field(default_factory=list)


class WorkspaceChatRequest(BaseModel):
    message: str


class PostCallDebriefRequest(BaseModel):
    notes: str = Field(min_length=10, max_length=20000)
    analysis: Optional[Dict[str, Any]] = None


class CommercialFitRequest(BaseModel):
    monthly_price: float = Field(ge=0)
    monthly_delivery_cost: float = Field(default=0, ge=0)
    contract_months: int = Field(default=12, ge=1, le=120)
    discount_percent: float = Field(default=0, ge=0, le=100)
    acquisition_cost: float = Field(default=0, ge=0)


class CalendarMeetingCreate(BaseModel):
    title: Optional[str] = None
    description: str = ""
    start_at: datetime
    end_at: datetime
    attendees: List[str] = Field(default_factory=list)


class CalendarMeetingUpdate(CalendarMeetingCreate):
    """Fields that can be changed when rescheduling a Calendar event."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def load_workspace(workspace_id: str) -> Dict[str, Any]:
    workspace = await db.get_workspace(workspace_id)

    if not workspace:
        raise HTTPException(
            status_code=404,
            detail="Workspace not found"
        )

    cache = WORKSPACE_CACHE.setdefault(
        workspace_id,
        {
            "accounts": [],
            "messages": []
        }
    )

    workspace["accounts"] = cache["accounts"]
    workspace["messages"] = cache["messages"]

    return workspace


async def background_product_task(
    search_id: str,
    product_name: str,
    product_description: str,
    user_id: str
):
    try:
        logger.info("Background product task started: %s", search_id)

        analysis = await run_product_pipeline(
            search_id,
            product_name,
            product_description
        )

        # Persist the LLM-generated ICP before company discovery.
        # Discovery reads target_industries from the search record.
        await db.update_search_icp(
            search_id,
            analysis,
            analysis.get("target_industries", [])
        )

        logger.info(
            "Saved ICP industries for %s: %s",
            search_id,
            analysis.get("target_industries", [])
        )

        capabilities = analysis.get("capabilities", [])
        value_props = analysis.get("value_propositions", [])

        ingested = await RAGService.ingest_product(
            search_id,
            product_name,
            product_description,
            capabilities,
            value_props
        )

        logger.info("Product RAG ingestion complete: %s chunks", ingested)

        await db.log_analytics(
            user_id,
            "product_analysis_completed",
            {
                "search_id": search_id,
                "capabilities_count": len(capabilities),
                "value_props_count": len(value_props)
            }
        )

        from backend.agents.discovery_agent import run_discovery_pipeline

        discovered = await run_discovery_pipeline(search_id)

        await db.log_analytics(
            user_id,
            "company_discovery_completed",
            {
                "search_id": search_id,
                "companies_count": len(discovered)
            }
        )

    except Exception as exc:
        logger.exception("Product pipeline failed: %s", exc)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "llm_provider": settings.LLM_PROVIDER,
        "database_mode": (
            "mock" if settings.USE_MOCK_DB else "postgresql"
        ),
        "rag_store": "chroma"
    }


@app.post("/api/workspaces")
async def create_workspace(payload: WorkspaceCreate):
    email = payload.email or "user@example.com"

    try:
        user_id = await db.get_user_id_by_email(email)

        workspace = await db.create_workspace(
            user_id=user_id,
            company_name=payload.company_name,
            company_description=payload.company_description,
            product_name=payload.product_name or "",
            product_description=payload.product_description or "",
            email=email
        )

        WORKSPACE_CACHE[workspace["id"]] = {
            "accounts": [],
            "messages": []
        }

        workspace["accounts"] = []
        workspace["messages"] = []

        return {
            "status": "success",
            "workspace": workspace
        }

    except Exception as exc:
        logger.exception("Workspace creation failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str):
    return await load_workspace(workspace_id)


@app.post("/api/workspaces/{workspace_id}/memory")
async def add_workspace_memory(
    workspace_id: str,
    payload: MemoryCreate
):
    await load_workspace(workspace_id)

    try:
        memory = await db.add_workspace_memory(
            workspace_id=workspace_id,
            fact=payload.fact,
            category=payload.category,
            approved=payload.approved
        )

        return {
            "status": "success",
            "memory": memory
        }

    except Exception as exc:
        logger.exception("Adding workspace memory failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/workspaces/{workspace_id}/memory")
async def get_workspace_memories(workspace_id: str):
    await load_workspace(workspace_id)

    try:
        memories = await db.get_workspace_memories(workspace_id)

        return {
            "memories": memories
        }

    except Exception as exc:
        logger.exception("Getting workspace memories failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/workspaces/{workspace_id}/accounts")
async def add_workspace_account(
    workspace_id: str,
    payload: AccountCreate
):
    await load_workspace(workspace_id)

    account = {
        "id": str(uuid.uuid4()),
        "name": payload.name,
        "domain": payload.domain,
        "industry": payload.industry,
        "description": payload.description,
        "fit_score": payload.fit_score,
        "confidence": payload.confidence,
        "evidence": payload.evidence,
        "status": "New",
        "created_at": now_iso()
    }

    WORKSPACE_CACHE[workspace_id]["accounts"].append(account)

    return {
        "status": "success",
        "account": account
    }


@app.get("/api/workspaces/{workspace_id}/accounts")
async def get_workspace_accounts(workspace_id: str):
    await load_workspace(workspace_id)

    return {
        "accounts": WORKSPACE_CACHE[workspace_id]["accounts"]
    }


@app.post("/api/workspaces/{workspace_id}/chat")
async def workspace_chat(
    workspace_id: str,
    payload: WorkspaceChatRequest
):
    workspace = await load_workspace(workspace_id)
    memories = await db.get_workspace_memories(workspace_id)

    approved_memories = [
        memory["fact"]
        for memory in memories
        if memory.get("approved") is True
    ]

    context = {
        "company_name": workspace["company_name"],
        "company_description": workspace["company_description"],
        "product_name": workspace["product_name"],
        "product_description": workspace["product_description"],
        "approved_memories": approved_memories,
        "accounts": workspace["accounts"]
    }

    prompt = f"""
You are an AI Revenue Chief of Staff.

Use only the workspace context below.
Do not invent company facts.
Be concise and helpful.

Workspace context:
{json.dumps(context, indent=2)}

User message:
{payload.message}
"""

    try:
        result = await get_chat_model(
            temperature=0.2
        ).ainvoke(prompt)

        answer = str(result.content).strip()

    except Exception as exc:
        logger.exception("Workspace chat failed")
        raise HTTPException(
            status_code=502,
            detail=f"Chat generation failed: {exc}"
        )

    timestamp = now_iso()

    WORKSPACE_CACHE[workspace_id]["messages"].append(
        {
            "role": "user",
            "content": payload.message,
            "created_at": timestamp
        }
    )

    WORKSPACE_CACHE[workspace_id]["messages"].append(
        {
            "role": "assistant",
            "content": answer,
            "created_at": now_iso()
        }
    )

    return {
        "workspace_id": workspace_id,
        "answer": answer
    }


@app.get("/api/workspaces/{workspace_id}/messages")
async def get_workspace_messages(workspace_id: str):
    await load_workspace(workspace_id)

    return {
        "messages": WORKSPACE_CACHE[workspace_id]["messages"]
    }


async def run_workspace_discovery_job(
    job_id: str,
    workspace_id: str
):
    try:
        JOBS[job_id]["status"] = "running"

        workspace = await load_workspace(workspace_id)

        user_id = await db.get_user_id_by_email(
            workspace["email"] or "user@example.com"
        )

        search = await db.create_search(
            user_id=user_id,
            product_name=workspace["product_name"],
            product_description=workspace["product_description"]
        )

        # A free Render instance must not leave a request running forever if
        # an upstream LLM or MCP subprocess stalls.
        analysis = await asyncio.wait_for(
            run_product_pipeline(
                search["id"],
                workspace["product_name"],
                workspace["product_description"]
            ),
            timeout=90
        )

        # Persist the LLM-generated ICP before company discovery.
        await db.update_search_icp(
            search["id"],
            analysis,
            analysis.get("target_industries", [])
        )

        logger.info(
            "Saved ICP industries for %s: %s",
            search["id"],
            analysis.get("target_industries", [])
        )

        capabilities = analysis.get("capabilities", [])
        value_props = analysis.get("value_propositions", [])

        await RAGService.ingest_product(
            search["id"],
            workspace["product_name"],
            workspace["product_description"],
            capabilities,
            value_props
        )

        from backend.agents.discovery_agent import run_discovery_pipeline

        companies = await asyncio.wait_for(
            run_discovery_pipeline(search["id"]),
            timeout=150
        )

        WORKSPACE_CACHE[workspace_id]["accounts"].extend(companies)

        JOBS[job_id]["status"] = "completed"
        JOBS[job_id]["companies_found"] = len(companies)
        JOBS[job_id]["search_id"] = search["id"]
        JOBS[job_id]["completed_at"] = now_iso()

    except asyncio.TimeoutError:
        logger.exception("Discovery timed out")

        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = (
            "Discovery timed out while contacting AI or research services. "
            "Please try again."
        )
        JOBS[job_id]["completed_at"] = now_iso()

    except Exception as exc:
        logger.exception("Discovery failed")

        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(exc) or (
            "Discovery failed in the backend. Check the Render logs for details."
        )
        JOBS[job_id]["completed_at"] = now_iso()


@app.post("/api/workspaces/{workspace_id}/jobs/discovery")
async def start_discovery_job(
    workspace_id: str,
    background_tasks: BackgroundTasks
):
    await load_workspace(workspace_id)

    job_id = str(uuid.uuid4())

    JOBS[job_id] = {
        "id": job_id,
        "workspace_id": workspace_id,
        "type": "company_discovery",
        "status": "queued",
        "created_at": now_iso()
    }

    background_tasks.add_task(
        run_workspace_discovery_job,
        job_id,
        workspace_id
    )

    return {
        "status": "started",
        "job": JOBS[job_id]
    }


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    return job


@app.post("/api/searches")
async def submit_product(
    payload: ProductSubmission,
    background_tasks: BackgroundTasks
):
    try:
        email = payload.email or "user@example.com"

        user_id = await db.get_user_id_by_email(email)

        search = await db.create_search(
            user_id=user_id,
            product_name=payload.product_name,
            product_description=payload.product_description
        )

        await db.log_analytics(
            user_id,
            "search_created",
            {
                "search_id": search["id"],
                "product_name": payload.product_name
            }
        )

        background_tasks.add_task(
            background_product_task,
            search["id"],
            payload.product_name,
            payload.product_description,
            user_id
        )

        return {
            "status": "initiated",
            "search_id": search["id"],
            "search": search
        }

    except Exception as exc:
        logger.exception("Product submission failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/searches/{search_id}/leads")
async def get_search_leads(search_id: str):
    try:
        return {
            "leads": await db.get_leads_by_search(search_id)
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/searches/{search_id}")
async def get_search_details(search_id: str):
    search = await db.get_search_details(search_id)

    if not search:
        raise HTTPException(
            status_code=404,
            detail="Search not found"
        )

    return search


@app.patch("/api/leads/{lead_id}/status")
async def update_lead_status(
    lead_id: str,
    payload: LeadStatusUpdate
):
    try:
        existing = await db.get_lead_with_company(lead_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Lead not found")

        old_status = existing.get("status")
        await db.update_lead_status(lead_id, payload.status)

        if old_status != payload.status:
            await db.record_lead_stage(
                lead_id=lead_id,
                old_stage=old_status,
                new_stage=payload.status,
                reason="Stage updated through the API"
            )

        return {
            "status": "success",
            "lead_id": lead_id,
            "old_status": old_status,
            "new_status": payload.status
        }

    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/leads/{lead_id}/events")
async def create_lead_event(
    lead_id: str,
    payload: LeadEventCreate
):
    try:
        if not await db.get_lead_with_company(lead_id):
            raise HTTPException(status_code=404, detail="Lead not found")

        event = await db.create_lead_event(
            lead_id=lead_id,
            event_type=payload.event_type,
            content=payload.content,
            source=payload.source,
            metadata=payload.metadata
        )

        return {
            "status": "success",
            "event": event
        }

    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/leads/{lead_id}/timeline")
async def get_lead_timeline(lead_id: str):
    try:
        if not await db.get_lead_with_company(lead_id):
            raise HTTPException(status_code=404, detail="Lead not found")

        return {
            "lead_id": lead_id,
            "events": await db.get_lead_events(lead_id),
            "stage_history": await db.get_lead_stage_history(lead_id)
        }

    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/workspaces/{workspace_id}/leads/{lead_id}/intelligence")
async def analyze_lead_intelligence(
    workspace_id: str,
    lead_id: str
):
    await load_workspace(workspace_id)

    try:
        from backend.agents.lead_intelligence_agent import (
            analyze_lead_intelligence as run_lead_intelligence
        )

        return {
            "status": "success",
            "result": await run_lead_intelligence(workspace_id, lead_id)
        }

    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Lead intelligence failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/workspaces/{workspace_id}/leads/{lead_id}/debrief")
async def post_call_debrief(workspace_id: str, lead_id: str, payload: PostCallDebriefRequest):
    """Analyze notes, or apply a previously reviewed debrief when analysis is supplied."""
    await load_workspace(workspace_id)
    try:
        from backend.agents.post_call_debrief_agent import analyze_post_call_debrief, apply_post_call_debrief

        if payload.analysis is not None:
            return await apply_post_call_debrief(workspace_id, lead_id, payload.notes, payload.analysis)
        return {"status": "review", "analysis": await analyze_post_call_debrief(lead_id, payload.notes)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Post-call debrief request failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/workspaces/{workspace_id}/leads/{lead_id}/commercial-fit")
async def commercial_fit(workspace_id: str, lead_id: str, payload: CommercialFitRequest):
    """Return an indicative profitability and budget estimate for a lead."""
    await load_workspace(workspace_id)
    try:
        from backend.agents.commercial_fit_agent import analyze_commercial_fit

        return {"status": "success", "analysis": await analyze_commercial_fit(lead_id, payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Commercial fit analysis failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/workspaces/{workspace_id}/tasks")
async def create_workspace_task(
    workspace_id: str,
    payload: TaskCreate
):
    await load_workspace(workspace_id)

    try:
        if payload.lead_id and not await db.get_lead_with_company(payload.lead_id):
            raise HTTPException(status_code=404, detail="Lead not found")

        task = await db.create_task(
            workspace_id=workspace_id,
            title=payload.title,
            description=payload.description,
            lead_id=payload.lead_id,
            priority=payload.priority,
            due_at=payload.due_at,
            source=payload.source
        )

        return {
            "status": "success",
            "task": task
        }

    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/workspaces/{workspace_id}/tasks/today")
async def get_today_tasks(workspace_id: str):
    await load_workspace(workspace_id)

    try:
        tasks = await db.get_tasks_for_workspace(workspace_id)
        today = datetime.now(timezone.utc).date()
        today_tasks = []

        for task in tasks:
            if not task.get("due_at"):
                today_tasks.append(task)
                continue

            due_at = datetime.fromisoformat(task["due_at"])
            if due_at.date() <= today:
                today_tasks.append(task)

        return {
            "workspace_id": workspace_id,
            "tasks": today_tasks
        }

    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(exc))


@app.patch("/api/tasks/{task_id}/complete")
async def complete_task(task_id: str):
    try:
        task = await db.complete_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        return {
            "status": "success",
            "task": task
        }

    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/email-drafts")
async def get_email_drafts(
    email: Optional[str] = "user@example.com"
):
    try:
        user_id = await db.get_user_id_by_email(
            email or "user@example.com"
        )

        return {
            "drafts": await db.get_email_drafts(user_id)
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/leads/{lead_id}/email")
async def regenerate_email(lead_id: str):
    try:
        from backend.mcp_server import generate_outreach_email

        return await generate_outreach_email(lead_id)

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/analytics")
async def get_analytics(
    email: Optional[str] = "user@example.com"
):
    try:
        user_id = await db.get_user_id_by_email(
            email or "user@example.com"
        )

        return await db.get_analytics_summary(user_id)

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/integrations/google/status")
async def google_connection_status(workspace_id: str):
    """Return whether the workspace has completed Google OAuth."""
    workspace = await load_workspace(workspace_id)
    connection = await db.get_google_connection(workspace["user_id"])
    return {
        "connected": bool(connection),
        "email": connection.get("email") if connection else None,
    }


@app.get("/api/integrations/google/connect")
async def connect_google(workspace_id: str):
    """Create a Google authorization URL for the Settings button."""
    await load_workspace(workspace_id)
    try:
        from backend.integrations.google_calendar import create_authorization_url

        return {"authorization_url": create_authorization_url(workspace_id)}
    except Exception as exc:
        logger.exception("Could not create Google authorization URL")
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/integrations/google/callback")
async def google_callback(code: str, state: str):
    """Receive Google's OAuth callback and return to the frontend."""
    try:
        from backend.integrations.google_calendar import exchange_code

        workspace_id, email, token_json = await asyncio.to_thread(exchange_code, code, state)
        workspace = await load_workspace(workspace_id)
        await db.save_google_connection(workspace["user_id"], email or workspace.get("email"), token_json)
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/?google=connected", status_code=303)
    except Exception as exc:
        logger.exception("Google OAuth callback failed")
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/workspaces/{workspace_id}/leads/{lead_id}/calendar")
async def schedule_lead_meeting(
    workspace_id: str,
    lead_id: str,
    payload: CalendarMeetingCreate,
):
    """Create a Calendar meeting for a lead after Google has been connected."""
    workspace = await load_workspace(workspace_id)
    lead = await db.get_lead_with_company(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if payload.end_at <= payload.start_at:
        raise HTTPException(status_code=400, detail="Meeting end time must be after start time")

    connection = await db.get_google_connection(workspace["user_id"])
    if not connection:
        raise HTTPException(status_code=409, detail="Connect Google Calendar in Settings first")

    start_at = payload.start_at
    end_at = payload.end_at
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)

    company_name = (lead.get("company") or {}).get("name") or "Lead meeting"
    title = payload.title or f"Meeting with {company_name}"
    description = payload.description or f"Outreach meeting for {company_name}."
    attendee_emails = list(payload.attendees)
    if lead.get("contact_email"):
        attendee_emails.append(lead["contact_email"])

    try:
        from backend.integrations.google_calendar import create_calendar_event, event_meet_link

        event, refreshed_token_json = await asyncio.to_thread(
            create_calendar_event,
            connection["token_json"],
            title,
            description,
            start_at.astimezone(timezone.utc).isoformat(),
            end_at.astimezone(timezone.utc).isoformat(),
            attendee_emails,
        )
        await db.save_google_connection(workspace["user_id"], connection.get("email"), refreshed_token_json)
        await db.create_lead_event(
            lead_id=lead_id,
            event_type="meeting_scheduled",
            content=f"{title} scheduled in Google Calendar.",
            source="google_calendar",
            metadata={
                "event_id": event.get("id"),
                "html_link": event.get("htmlLink"),
                "meet_link": event_meet_link(event),
                "title": title,
                "description": description,
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "attendees": attendee_emails,
            },
        )
        return {
            "status": "success",
            "event_id": event.get("id"),
            "html_link": event.get("htmlLink"),
            "meet_link": event_meet_link(event),
        }
    except Exception as exc:
        logger.exception("Calendar event creation failed")
        raise HTTPException(status_code=502, detail=f"Google Calendar could not create the meeting: {exc}")


@app.patch("/api/workspaces/{workspace_id}/leads/{lead_id}/calendar/{event_id}")
async def reschedule_lead_meeting(
    workspace_id: str,
    lead_id: str,
    event_id: str,
    payload: CalendarMeetingUpdate,
):
    """Reschedule an existing Google Calendar meeting for a lead."""
    workspace = await load_workspace(workspace_id)
    lead = await db.get_lead_with_company(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if payload.end_at <= payload.start_at:
        raise HTTPException(status_code=400, detail="Meeting end time must be after start time")

    connection = await db.get_google_connection(workspace["user_id"])
    if not connection:
        raise HTTPException(status_code=409, detail="Connect Google Calendar in Settings first")
    start_at = payload.start_at if payload.start_at.tzinfo else payload.start_at.replace(tzinfo=timezone.utc)
    end_at = payload.end_at if payload.end_at.tzinfo else payload.end_at.replace(tzinfo=timezone.utc)
    company_name = (lead.get("company") or {}).get("name") or "Lead meeting"
    title = payload.title or f"Meeting with {company_name}"
    description = payload.description or f"Outreach meeting for {company_name}."
    attendees = list(payload.attendees)
    if lead.get("contact_email"):
        attendees.append(lead["contact_email"])

    try:
        from backend.integrations.google_calendar import event_meet_link, update_calendar_event

        event, refreshed_token_json = await asyncio.to_thread(
            update_calendar_event,
            connection["token_json"], event_id, title, description,
            start_at.astimezone(timezone.utc).isoformat(),
            end_at.astimezone(timezone.utc).isoformat(), attendees,
        )
        await db.save_google_connection(workspace["user_id"], connection.get("email"), refreshed_token_json)
        await db.create_lead_event(
            lead_id=lead_id,
            event_type="meeting_rescheduled",
            content=f"{title} rescheduled in Google Calendar.",
            source="google_calendar",
            metadata={
                "event_id": event.get("id", event_id),
                "html_link": event.get("htmlLink"),
                "meet_link": event_meet_link(event),
                "title": title,
                "description": description,
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "attendees": attendees,
            },
        )
        return {"status": "success", "event_id": event.get("id", event_id), "html_link": event.get("htmlLink"), "meet_link": event_meet_link(event)}
    except Exception as exc:
        logger.exception("Calendar event update failed")
        raise HTTPException(status_code=502, detail=f"Google Calendar could not reschedule the meeting: {exc}")


@app.delete("/api/workspaces/{workspace_id}/leads/{lead_id}/calendar/{event_id}")
async def cancel_lead_meeting(workspace_id: str, lead_id: str, event_id: str):
    """Cancel an existing Google Calendar meeting for a lead."""
    workspace = await load_workspace(workspace_id)
    lead = await db.get_lead_with_company(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    connection = await db.get_google_connection(workspace["user_id"])
    if not connection:
        raise HTTPException(status_code=409, detail="Connect Google Calendar in Settings first")
    try:
        from backend.integrations.google_calendar import cancel_calendar_event

        refreshed_token_json = await asyncio.to_thread(cancel_calendar_event, connection["token_json"], event_id)
        await db.save_google_connection(workspace["user_id"], connection.get("email"), refreshed_token_json)
        await db.create_lead_event(
            lead_id=lead_id,
            event_type="meeting_cancelled",
            content="Meeting cancelled in Google Calendar.",
            source="google_calendar",
            metadata={"event_id": event_id},
        )
        return {"status": "success", "event_id": event_id}
    except Exception as exc:
        logger.exception("Calendar event cancellation failed")
        raise HTTPException(status_code=502, detail=f"Google Calendar could not cancel the meeting: {exc}")


@app.get("/api/chat/stream")
async def stream_chat(
    request: Request,
    message: str = Query(min_length=1, max_length=4000),
    session_id: Optional[str] = None
):
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is not configured"
        )

    trace = RequestTrace()
    session = session_id or str(uuid.uuid4())

    async def run():
        try:
            await run_chat(session, message.strip(), trace)

            await trace.publish(
                "done",
                {
                    "session_id": session,
                    "search_id": trace.search_id
                }
            )

        except Exception:
            logger.exception(
                "Generation failed: %s",
                trace.request_id
            )

            await trace.publish(
                "error",
                {
                    "message": "Generation failed. Please retry."
                }
            )

        finally:
            await trace.close()

    async def events():
        task = asyncio.create_task(run())

        await trace.publish(
            "trace",
            {
                "request_id": trace.request_id,
                "search_id": trace.search_id,
                "session_id": session
            }
        )

        try:
            while True:
                if await request.is_disconnected():
                    task.cancel()
                    break

                event = await trace.events.get()

                if event is None:
                    break

                yield (
                    f"event: {event['event']}\n"
                    f"data: {json.dumps(event['data'])}\n\n"
                )

        finally:
            if not task.done():
                task.cancel()

            await asyncio.gather(
                task,
                return_exceptions=True
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )
