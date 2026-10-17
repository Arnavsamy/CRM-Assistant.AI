import asyncio
import os
import uuid
import logging
import json
from typing import Dict, List, Any, Optional
import datetime
import numpy as np

from backend.config import settings

logger = logging.getLogger(__name__)

# Simple in-memory storage for Mock mode
_mock_db: Dict[str, List[Dict[str, Any]]] = {
    "users": [],
    "searches": [],
    "product_documents": [],
    "companies": [],
    "company_documents": [],
    "company_evidence": [],
    "leads": [],
    "email_drafts": [],
    "analytics": [],
    "workspaces": [],
    "workspace_memories": [],
    "lead_events": [],
    "lead_stage_history": [],
    "tasks": [],
    "google_connections": [],
}

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    a = np.array(v1)
    b = np.array(v2)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))

class AsyncDatabase:
    """Asynchronous database interface for PostgreSQL or local Mock fallback."""

    def __init__(self):
        self.use_mock = settings.USE_MOCK_DB
        self.pool = None
        self._pool_lock = asyncio.Lock()
        if not self.use_mock:
            # Pool will be lazily initialized on the first query
            pass

    async def get_pool(self):
        if self.use_mock:
            return None
        if self.pool is None:
            async with self._pool_lock:
                if self.pool is None and not self.use_mock:
                    import asyncpg
                    try:
                        pool = await asyncpg.create_pool(settings.DATABASE_URL)
                        # Ensure the workspace table exists for databases created
                        # from older schema versions before the workspace feature.
                        await pool.execute(
                            """
                            CREATE TABLE IF NOT EXISTS workspaces (
                                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                                user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                                company_name text NOT NULL,
                                company_description text NOT NULL,
                                product_name text NOT NULL,
                                product_description text NOT NULL,
                                email text NOT NULL,
                                created_at timestamptz NOT NULL DEFAULT now()
                            )
                            """
                        )
                        await pool.execute(
                            """
                            CREATE TABLE IF NOT EXISTS workspace_memories (
                                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                                workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                                fact text NOT NULL,
                                category text NOT NULL DEFAULT 'business',
                                approved boolean NOT NULL DEFAULT false,
                                created_at timestamptz NOT NULL DEFAULT now()
                            )
                            """
                        )
                        # Keep local development databases usable when the new
                        # table has not been recreated from database/init.sql.
                        await pool.execute(
                            """
                            CREATE TABLE IF NOT EXISTS google_connections (
                                user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                                email text,
                                token_json text NOT NULL,
                                updated_at timestamptz NOT NULL DEFAULT now()
                            )
                            """
                        )
                        self.pool = pool
                        logger.info("Connected to live PostgreSQL DB.")
                    except Exception as e:
                        logger.error(f"Failed to connect to live PostgreSQL: {e}. Falling back to mock DB.")
                        self.use_mock = True
        return self.pool

    async def get_user_id_by_email(self, email: str) -> str:
        """Retrieves or creates a user ID by email."""
        if self.use_mock:
            for user in _mock_db["users"]:
                if user["email"] == email:
                    return user["id"]
            new_id = str(uuid.uuid4())
            _mock_db["users"].append({
                "id": new_id,
                "email": email,
                "created_at": datetime.datetime.utcnow().isoformat()
            })
            return new_id
        else:
            pool = await self.get_pool()
            row = await pool.fetchrow("SELECT id FROM users WHERE email = $1", email)
            if row:
                return str(row["id"])
            new_id = str(uuid.uuid4())
            await pool.execute("INSERT INTO users (id, email) VALUES ($1, $2)", uuid.UUID(new_id), email)
            return new_id

    async def create_search(self, user_id: str, product_name: str, product_description: str) -> Dict[str, Any]:
        """Creates a search entry."""
        search_id = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow()

        if self.use_mock:
            data = {
                "id": search_id,
                "user_id": user_id,
                "product_name": product_name,
                "product_description": product_description,
                "icp_definition": {},
                "target_industries": [],
                "created_at": created_at.isoformat()
            }
            _mock_db["searches"].append(data)
            return data
        else:
            pool = await self.get_pool()
            await pool.execute(
                "INSERT INTO searches (id, user_id, product_name, product_description, icp_definition, target_industries, created_at) "
                "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)",
                uuid.UUID(search_id), uuid.UUID(user_id), product_name, product_description,
                json.dumps({}), json.dumps([]), created_at
            )
            return {
                "id": search_id,
                "user_id": user_id,
                "product_name": product_name,
                "product_description": product_description,
                "icp_definition": {},
                "target_industries": [],
                "created_at": created_at.isoformat()
            }

    async def get_search_details(self, search_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a search entry by ID."""
        if self.use_mock:
            return next((s for s in _mock_db["searches"] if s["id"] == search_id), None)
        else:
            pool = await self.get_pool()
            row = await pool.fetchrow("SELECT * FROM searches WHERE id = $1", uuid.UUID(search_id))
            if not row:
                return None
            return {
                "id": str(row["id"]),
                "user_id": str(row["user_id"]),
                "product_name": row["product_name"],
                "product_description": row["product_description"],
                "icp_definition": json.loads(row["icp_definition"]) if isinstance(row["icp_definition"], str) else row["icp_definition"],
                "target_industries": json.loads(row["target_industries"]) if isinstance(row["target_industries"], str) else row["target_industries"],
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"]
            }

    async def update_search_icp(self, search_id: str, icp_definition: Dict[str, Any], target_industries: List[Any]) -> None:
        """Updates a search entry with ICP and Industries."""
        if self.use_mock:
            for s in _mock_db["searches"]:
                if s["id"] == search_id:
                    s["icp_definition"] = icp_definition
                    s["target_industries"] = target_industries
                    break
        else:
            pool = await self.get_pool()
            await pool.execute(
                "UPDATE searches SET icp_definition = $1::jsonb, target_industries = $2::jsonb WHERE id = $3",
                json.dumps(icp_definition), json.dumps(target_industries), uuid.UUID(search_id)
            )

    async def create_workspace(
        self,
        user_id: str,
        company_name: str,
        company_description: str,
        product_name: str,
        product_description: str,
        email: str
    ) -> Dict[str, Any]:
        workspace_id = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow()

        data = {
            "id": workspace_id,
            "user_id": user_id,
            "company_name": company_name,
            "company_description": company_description,
            "product_name": product_name,
            "product_description": product_description,
            "email": email,
            "created_at": created_at.isoformat()
        }

        if self.use_mock:
            _mock_db.setdefault("workspaces", []).append(data)
            return data

        pool = await self.get_pool()

        await pool.execute(
            """
            INSERT INTO workspaces
            (id, user_id, company_name, company_description,
            product_name, product_description, email, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            uuid.UUID(workspace_id),
            uuid.UUID(user_id),
            company_name,
            company_description,
            product_name,
            product_description,
            email,
            created_at
        )

        return data

    async def get_workspace(
        self,
        workspace_id: str
    ) -> Optional[Dict[str, Any]]:
        if self.use_mock:
            return next(
                (
                    w for w in _mock_db.get("workspaces", [])
                    if w["id"] == workspace_id
                ),
                None
            )

        pool = await self.get_pool()

        row = await pool.fetchrow(
            "SELECT * FROM workspaces WHERE id = $1",
            uuid.UUID(workspace_id)
        )

        if not row:
            return None

        return {
            "id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "company_name": row["company_name"],
            "company_description": row["company_description"],
            "product_name": row["product_name"],
            "product_description": row["product_description"],
            "email": row["email"],
            "created_at": row["created_at"].isoformat()
        }

    async def save_google_connection(
        self,
        user_id: str,
        email: Optional[str],
        token_json: str
    ) -> None:
        """Stores the OAuth token payload for the connected workspace user."""
        updated_at = datetime.datetime.utcnow()
        if self.use_mock:
            data = {
                "user_id": user_id,
                "email": email,
                "token_json": token_json,
                "updated_at": updated_at.isoformat(),
            }
            _mock_db["google_connections"] = [
                item for item in _mock_db["google_connections"]
                if item["user_id"] != user_id
            ]
            _mock_db["google_connections"].append(data)
            return

        pool = await self.get_pool()
        await pool.execute(
            """
            INSERT INTO google_connections (user_id, email, token_json, updated_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE SET
                email = EXCLUDED.email,
                token_json = EXCLUDED.token_json,
                updated_at = EXCLUDED.updated_at
            """,
            uuid.UUID(user_id), email, token_json, updated_at
        )

    async def get_google_connection(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Returns the saved Google OAuth connection for a user."""
        if self.use_mock:
            return next(
                (item for item in _mock_db["google_connections"] if item["user_id"] == user_id),
                None,
            )

        pool = await self.get_pool()
        row = await pool.fetchrow(
            "SELECT user_id, email, token_json, updated_at FROM google_connections WHERE user_id = $1",
            uuid.UUID(user_id),
        )
        if not row:
            return None
        return {
            "user_id": str(row["user_id"]),
            "email": row["email"],
            "token_json": row["token_json"],
            "updated_at": row["updated_at"].isoformat(),
        }

    async def add_workspace_memory(
        self,
        workspace_id: str,
        fact: str,
        category: str,
        approved: bool
    ) -> Dict[str, Any]:
        memory_id = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow()

        data = {
            "id": memory_id,
            "workspace_id": workspace_id,
            "fact": fact,
            "category": category,
            "approved": approved,
            "created_at": created_at.isoformat()
        }

        if self.use_mock:
            _mock_db.setdefault("workspace_memories", []).append(data)
            return data

        pool = await self.get_pool()

        await pool.execute(
            """
            INSERT INTO workspace_memories
            (id, workspace_id, fact, category, approved, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            uuid.UUID(memory_id),
            uuid.UUID(workspace_id),
            fact,
            category,
            approved,
            created_at
        )

        return data

    async def get_workspace_memories(
        self,
        workspace_id: str
    ) -> List[Dict[str, Any]]:
        if self.use_mock:
            return [
                m for m in _mock_db.get("workspace_memories", [])
                if m["workspace_id"] == workspace_id
            ]

        pool = await self.get_pool()

        rows = await pool.fetch(
            """
            SELECT * FROM workspace_memories
            WHERE workspace_id = $1
            ORDER BY created_at DESC
            """,
            uuid.UUID(workspace_id)
        )

        return [
            {
                "id": str(row["id"]),
                "workspace_id": str(row["workspace_id"]),
                "fact": row["fact"],
                "category": row["category"],
                "approved": row["approved"],
                "created_at": row["created_at"].isoformat()
            }
            for row in rows
        ]

    async def insert_product_document(self, search_id: str, content: str, embedding: List[float], metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Inserts a product capabilities document with its vector embedding."""
        doc_id = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow()

        if self.use_mock:
            data = {
                "id": doc_id,
                "search_id": search_id,
                "content": content,
                "embedding": embedding,
                "metadata": metadata,
                "created_at": created_at.isoformat()
            }
            _mock_db["product_documents"].append(data)
            return data
        else:
            pool = await self.get_pool()
            embedding_str = f"[{','.join(map(str, embedding))}]"
            await pool.execute(
                "INSERT INTO product_documents (id, search_id, content, embedding, metadata, created_at) "
                "VALUES ($1, $2, $3, $4::vector, $5::jsonb, $6)",
                uuid.UUID(doc_id), uuid.UUID(search_id), content, embedding_str, json.dumps(metadata), created_at
            )
            return {
                "id": doc_id,
                "search_id": search_id,
                "content": content,
                "embedding": embedding,
                "metadata": metadata,
                "created_at": created_at.isoformat()
            }

    async def search_product_documents(self, search_id: str, query_embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        """Performs pgvector cosine similarity search on product documents."""
        if self.use_mock:
            docs = [d for d in _mock_db["product_documents"] if d["search_id"] == search_id]
            scored = []
            for d in docs:
                sim = cosine_similarity(query_embedding, d["embedding"])
                scored.append((sim, d))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [dict(item[1], similarity=item[0]) for item in scored[:limit]]
        else:
            pool = await self.get_pool()
            embedding_str = f"[{','.join(map(str, query_embedding))}]"
            rows = await pool.fetch(
                "SELECT id, content, metadata, created_at, (1 - (embedding <=> $1::vector)) AS similarity "
                "FROM product_documents WHERE search_id = $2 "
                "ORDER BY embedding <=> $1::vector LIMIT $3",
                embedding_str, uuid.UUID(search_id), limit
            )
            return [
                {
                    "id": str(r["id"]),
                    "content": r["content"],
                    "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                    "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"],
                    "similarity": float(r["similarity"])
                }
                for r in rows
            ]

    async def insert_company(self, search_id: str, name: str, domain: str, industry: str, description: str, website: str, match_score: int, why_recommended: str, pain_points: List[str]) -> Dict[str, Any]:
        """Inserts a company and creates a Lead automatically in 'New' status."""
        company_id = str(uuid.uuid4())
        lead_id = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow()

        company_data = {
            "id": company_id,
            "search_id": search_id,
            "name": name,
            "domain": domain,
            "industry": industry,
            "description": description,
            "website": website,
            "match_score": match_score,
            "why_recommended": why_recommended,
            "pain_points": pain_points,
            "created_at": created_at.isoformat()
        }

        if self.use_mock:
            _mock_db["companies"].append(company_data)
            _mock_db["leads"].append({
                "id": lead_id,
                "company_id": company_id,
                "search_id": search_id,
                "status": "New",
                "contact_name": None,
                "contact_email": None,
                "created_at": created_at.isoformat()
            })
        else:
            pool = await self.get_pool()
            await pool.execute(
                "INSERT INTO companies (id, search_id, name, domain, industry, description, website, match_score, why_recommended, pain_points, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)",
                uuid.UUID(company_id), uuid.UUID(search_id), name, domain, industry, description, website, match_score, why_recommended,
                json.dumps(pain_points), created_at
            )
            await pool.execute(
                "INSERT INTO leads (id, company_id, search_id, status, contact_name, contact_email, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                uuid.UUID(lead_id), uuid.UUID(company_id), uuid.UUID(search_id), "New", None, None, created_at
            )

        return company_data

    async def save_company_evidence(
        self,
        company_id: str,
        source_url: str,
        evidence_text: str,
        verified: bool
    ) -> Dict[str, Any]:
        evidence_id = str(uuid.uuid4())
        collected_at = datetime.datetime.utcnow()

        data = {
            "id": evidence_id,
            "company_id": company_id,
            "source_url": source_url,
            "evidence_text": evidence_text,
            "verified": verified,
            "collected_at": collected_at.isoformat()
        }
        if self.use_mock:
            _mock_db["company_evidence"].append(data)
            return data
        pool = await self.get_pool()

        await pool.execute(
            """
            INSERT INTO company_evidence
            (id, company_id, source_url, evidence_text, verified, collected_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            uuid.UUID(evidence_id),
            uuid.UUID(company_id),
            source_url,
            evidence_text,
            verified,
            collected_at
        )
        return data

    async def insert_company_document(self, company_id: str, content: str, embedding: List[float], metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Inserts researched company documentation for RAG analysis."""
        doc_id = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow()

        if self.use_mock:
            data = {
                "id": doc_id,
                "company_id": company_id,
                "content": content,
                "embedding": embedding,
                "metadata": metadata,
                "created_at": created_at.isoformat()
            }
            _mock_db["company_documents"].append(data)
            return data
        else:
            pool = await self.get_pool()
            embedding_str = f"[{','.join(map(str, embedding))}]"
            res = await pool.execute(
                "INSERT INTO company_documents (id, company_id, content, embedding, metadata, created_at) "
                "VALUES ($1, $2, $3, $4::vector, $5::jsonb, $6)",
                uuid.UUID(doc_id), uuid.UUID(company_id), content, embedding_str, json.dumps(metadata), created_at
            )
            return {
                "id": doc_id,
                "company_id": company_id,
                "content": content,
                "embedding": embedding,
                "metadata": metadata,
                "created_at": created_at.isoformat()
            }

    async def search_company_documents(self, company_id: str, query_embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        """Performs pgvector cosine similarity search on company documents."""
        if self.use_mock:
            docs = [d for d in _mock_db["company_documents"] if d["company_id"] == company_id]
            scored = []
            for d in docs:
                sim = cosine_similarity(query_embedding, d["embedding"])
                scored.append((sim, d))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [dict(item[1], similarity=item[0]) for item in scored[:limit]]
        else:
            pool = await self.get_pool()
            embedding_str = f"[{','.join(map(str, query_embedding))}]"
            rows = await pool.fetch(
                "SELECT id, content, metadata, created_at, (1 - (embedding <=> $1::vector)) AS similarity "
                "FROM company_documents WHERE company_id = $2 "
                "ORDER BY embedding <=> $1::vector LIMIT $3",
                embedding_str, uuid.UUID(company_id), limit
            )
            return [
                {
                    "id": str(r["id"]),
                    "content": r["content"],
                    "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                    "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"],
                    "similarity": float(r["similarity"])
                }
                for r in rows
            ]

    async def get_companies_by_search(self, search_id: str) -> List[Dict[str, Any]]:
        """Retrieves all companies associated with a search ID."""
        if self.use_mock:
            return [c for c in _mock_db["companies"] if c["search_id"] == search_id]
        else:
            pool = await self.get_pool()
            rows = await pool.fetch("SELECT * FROM companies WHERE search_id = $1", uuid.UUID(search_id))
            return [
                {
                    "id": str(r["id"]),
                    "search_id": str(r["search_id"]),
                    "name": r["name"],
                    "domain": r["domain"],
                    "industry": r["industry"],
                    "description": r["description"],
                    "website": r["website"],
                    "match_score": r["match_score"],
                    "why_recommended": r["why_recommended"],
                    "pain_points": json.loads(r["pain_points"]) if isinstance(r["pain_points"], str) else r["pain_points"],
                    "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"]
                }
                for r in rows
            ]

    async def get_leads_by_search(self, search_id: str) -> List[Dict[str, Any]]:
        """Retrieves all leads associated with a search ID, including company details."""
        if self.use_mock:
            leads = [l for l in _mock_db["leads"] if l["search_id"] == search_id]
            for l in leads:
                for c in _mock_db["companies"]:
                    if c["id"] == l["company_id"]:
                        l["company"] = c
                        break
            return leads
        else:
            pool = await self.get_pool()
            rows = await pool.fetch(
                "SELECT l.*, row_to_json(c.*) as company "
                "FROM leads l JOIN companies c ON l.company_id = c.id "
                "WHERE l.search_id = $1",
                uuid.UUID(search_id)
            )
            leads = []
            for r in rows:
                comp = json.loads(r["company"]) if isinstance(r["company"], str) else r["company"]
                if comp:
                    comp["id"] = str(comp["id"])
                    comp["search_id"] = str(comp["search_id"])
                    if isinstance(comp.get("pain_points"), str):
                        comp["pain_points"] = json.loads(comp["pain_points"])
                leads.append({
                    "id": str(r["id"]),
                    "company_id": str(r["company_id"]),
                    "search_id": str(r["search_id"]),
                    "status": r["status"],
                    "contact_name": r["contact_name"],
                    "contact_email": r["contact_email"],
                    "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"],
                    "company": comp
                })
            return leads

    async def get_lead_with_company(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a lead and its company directly from PostgreSQL."""
        if self.use_mock:
            lead = next((item for item in _mock_db["leads"] if item["id"] == lead_id), None)
            if not lead:
                return None
            company = next((item for item in _mock_db["companies"] if item["id"] == lead["company_id"]), None)
            return dict(lead, company=company)

        pool = await self.get_pool()
        row = await pool.fetchrow(
            "SELECT l.*, row_to_json(c.*) AS company FROM leads l JOIN companies c ON c.id = l.company_id WHERE l.id = $1",
            uuid.UUID(lead_id),
        )
        if not row:
            return None
        company = json.loads(row["company"]) if isinstance(row["company"], str) else row["company"]
        company["id"] = str(company["id"])
        company["search_id"] = str(company["search_id"])
        if isinstance(company.get("pain_points"), str):
            company["pain_points"] = json.loads(company["pain_points"])
        return {
            "id": str(row["id"]), "company_id": str(row["company_id"]), "search_id": str(row["search_id"]),
            "status": row["status"], "contact_name": row["contact_name"], "contact_email": row["contact_email"],
            "company": company,
        }

    async def update_lead_status(self, lead_id: str, status: str) -> None:
        """Updates lead status in the CRM."""
        if self.use_mock:
            for l in _mock_db["leads"]:
                if l["id"] == lead_id:
                    l["status"] = status
                    break
        else:
            pool = await self.get_pool()
            await pool.execute("UPDATE leads SET status = $1 WHERE id = $2", status, uuid.UUID(lead_id))

    async def create_lead_event(
        self,
        lead_id: str,
        event_type: str,
        content: str,
        source: str = "manual",
        metadata: Optional[Dict[str, Any]] = None,
        occurred_at: Optional[datetime.datetime] = None
    ) -> Dict[str, Any]:
        """Stores an email, call, meeting, CRM note, or other lead activity."""
        event_id = str(uuid.uuid4())
        occurred = occurred_at or datetime.datetime.utcnow()
        metadata = metadata or {}
        created = datetime.datetime.utcnow()

        data = {
            "id": event_id,
            "lead_id": lead_id,
            "event_type": event_type,
            "content": content,
            "source": source,
            "metadata": metadata,
            "occurred_at": occurred.isoformat(),
            "created_at": created.isoformat()
        }

        if self.use_mock:
            _mock_db["lead_events"].append(data)
            return data

        pool = await self.get_pool()
        await pool.execute(
            """
            INSERT INTO lead_events
            (id, lead_id, event_type, content, source, metadata, occurred_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            """,
            uuid.UUID(event_id), uuid.UUID(lead_id), event_type,
            content, source, json.dumps(metadata), occurred
        )
        return data

    async def get_lead_events(self, lead_id: str) -> List[Dict[str, Any]]:
        """Returns a lead's activity timeline, newest activity first."""
        if self.use_mock:
            events = [
                item for item in _mock_db["lead_events"]
                if item["lead_id"] == lead_id
            ]
            return sorted(events, key=lambda item: item["occurred_at"], reverse=True)

        pool = await self.get_pool()
        rows = await pool.fetch(
            "SELECT * FROM lead_events WHERE lead_id = $1 ORDER BY occurred_at DESC",
            uuid.UUID(lead_id)
        )
        return [
            {
                "id": str(row["id"]),
                "lead_id": str(row["lead_id"]),
                "event_type": row["event_type"],
                "content": row["content"],
                "source": row["source"],
                "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
                "occurred_at": row["occurred_at"].isoformat(),
                "created_at": row["created_at"].isoformat()
            }
            for row in rows
        ]

    async def record_lead_stage(
        self,
        lead_id: str,
        new_stage: str,
        old_stage: Optional[str] = None,
        reason: str = "",
        confidence: Optional[int] = None
    ) -> Dict[str, Any]:
        """Records why a lead moved between pipeline stages."""
        history_id = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow()
        data = {
            "id": history_id,
            "lead_id": lead_id,
            "old_stage": old_stage,
            "new_stage": new_stage,
            "reason": reason,
            "confidence": confidence,
            "created_at": created_at.isoformat()
        }

        if self.use_mock:
            _mock_db["lead_stage_history"].append(data)
            return data

        pool = await self.get_pool()
        await pool.execute(
            """
            INSERT INTO lead_stage_history
            (id, lead_id, old_stage, new_stage, reason, confidence, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            uuid.UUID(history_id), uuid.UUID(lead_id), old_stage,
            new_stage, reason, confidence, created_at
        )
        return data

    async def get_lead_stage_history(self, lead_id: str) -> List[Dict[str, Any]]:
        """Returns the stage-change history for a lead."""
        if self.use_mock:
            history = [
                item for item in _mock_db["lead_stage_history"]
                if item["lead_id"] == lead_id
            ]
            return sorted(history, key=lambda item: item["created_at"], reverse=True)

        pool = await self.get_pool()
        rows = await pool.fetch(
            "SELECT * FROM lead_stage_history WHERE lead_id = $1 ORDER BY created_at DESC",
            uuid.UUID(lead_id)
        )
        return [
            {
                "id": str(row["id"]),
                "lead_id": str(row["lead_id"]),
                "old_stage": row["old_stage"],
                "new_stage": row["new_stage"],
                "reason": row["reason"],
                "confidence": row["confidence"],
                "created_at": row["created_at"].isoformat()
            }
            for row in rows
        ]

    async def create_task(
        self,
        workspace_id: str,
        title: str,
        description: str = "",
        lead_id: Optional[str] = None,
        priority: str = "medium",
        due_at: Optional[datetime.datetime] = None,
        source: str = "ai"
    ) -> Dict[str, Any]:
        """Creates a workspace task or AI recommendation."""
        task_id = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow()
        data = {
            "id": task_id,
            "workspace_id": workspace_id,
            "lead_id": lead_id,
            "title": title,
            "description": description,
            "status": "open",
            "priority": priority,
            "due_at": due_at.isoformat() if due_at else None,
            "source": source,
            "created_at": created_at.isoformat(),
            "completed_at": None
        }

        if self.use_mock:
            _mock_db["tasks"].append(data)
            return data

        pool = await self.get_pool()
        await pool.execute(
            """
            INSERT INTO tasks
            (id, workspace_id, lead_id, title, description, status,
             priority, due_at, source, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            uuid.UUID(task_id), uuid.UUID(workspace_id),
            uuid.UUID(lead_id) if lead_id else None,
            title, description, "open", priority, due_at, source, created_at
        )
        return data

    async def get_tasks_for_workspace(
        self,
        workspace_id: str,
        include_completed: bool = False
    ) -> List[Dict[str, Any]]:
        """Returns workspace tasks, with open tasks first."""
        if self.use_mock:
            tasks = [
                task for task in _mock_db["tasks"]
                if task["workspace_id"] == workspace_id
                and (include_completed or task["status"] != "completed")
            ]
            return sorted(
                tasks,
                key=lambda item: (item["status"] == "completed", item["created_at"])
            )

        pool = await self.get_pool()
        if include_completed:
            rows = await pool.fetch(
                "SELECT * FROM tasks WHERE workspace_id = $1 ORDER BY status, due_at NULLS LAST, created_at DESC",
                uuid.UUID(workspace_id)
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM tasks WHERE workspace_id = $1 AND status <> 'completed' ORDER BY due_at NULLS LAST, created_at DESC",
                uuid.UUID(workspace_id)
            )

        return [
            {
                "id": str(row["id"]),
                "workspace_id": str(row["workspace_id"]),
                "lead_id": str(row["lead_id"]) if row["lead_id"] else None,
                "title": row["title"],
                "description": row["description"],
                "status": row["status"],
                "priority": row["priority"],
                "due_at": row["due_at"].isoformat() if row["due_at"] else None,
                "source": row["source"],
                "created_at": row["created_at"].isoformat(),
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None
            }
            for row in rows
        ]

    async def complete_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Marks a task as completed."""
        completed_at = datetime.datetime.utcnow()

        if self.use_mock:
            task = next((item for item in _mock_db["tasks"] if item["id"] == task_id), None)
            if not task:
                return None
            task["status"] = "completed"
            task["completed_at"] = completed_at.isoformat()
            return task

        pool = await self.get_pool()
        row = await pool.fetchrow(
            "UPDATE tasks SET status = 'completed', completed_at = $1 WHERE id = $2 RETURNING *",
            completed_at, uuid.UUID(task_id)
        )
        if not row:
            return None
        return {
            "id": str(row["id"]),
            "workspace_id": str(row["workspace_id"]),
            "lead_id": str(row["lead_id"]) if row["lead_id"] else None,
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "priority": row["priority"],
            "due_at": row["due_at"].isoformat() if row["due_at"] else None,
            "source": row["source"],
            "created_at": row["created_at"].isoformat(),
            "completed_at": row["completed_at"].isoformat()
        }

    async def create_email_draft(self, lead_id: str, subject: str, body: str) -> Dict[str, Any]:
        """Creates an email draft for a lead."""
        draft_id = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow()

        if self.use_mock:
            _mock_db["email_drafts"] = [d for d in _mock_db["email_drafts"] if d["lead_id"] != lead_id]
            data = {
                "id": draft_id,
                "lead_id": lead_id,
                "subject": subject,
                "body": body,
                "status": "Draft",
                "created_at": created_at.isoformat()
            }
            _mock_db["email_drafts"].append(data)
            return data
        else:
            pool = await self.get_pool()
            await pool.execute("DELETE FROM email_drafts WHERE lead_id = $1", uuid.UUID(lead_id))
            await pool.execute(
                "INSERT INTO email_drafts (id, lead_id, subject, body, status, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                uuid.UUID(draft_id), uuid.UUID(lead_id), subject, body, "Draft", created_at
            )
            return {
                "id": draft_id,
                "lead_id": lead_id,
                "subject": subject,
                "body": body,
                "status": "Draft",
                "created_at": created_at.isoformat()
            }

    async def get_email_drafts(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieves email drafts for a user."""
        if self.use_mock:
            drafts = []
            for d in _mock_db["email_drafts"]:
                lead = next((l for l in _mock_db["leads"] if l["id"] == d["lead_id"]), None)
                if lead:
                    company = next((c for c in _mock_db["companies"] if c["id"] == lead["company_id"]), None)
                    d["lead"] = lead
                    d["company"] = company
                    drafts.append(d)
            return drafts
        else:
            pool = await self.get_pool()
            rows = await pool.fetch(
                "SELECT d.*, row_to_json(l.*) as lead, row_to_json(c.*) as company "
                "FROM email_drafts d "
                "JOIN leads l ON d.lead_id = l.id "
                "JOIN companies c ON l.company_id = c.id "
                "JOIN searches s ON l.search_id = s.id "
                "WHERE s.user_id = $1",
                uuid.UUID(user_id)
            )
            drafts = []
            for r in rows:
                lead = json.loads(r["lead"]) if isinstance(r["lead"], str) else r["lead"]
                company = json.loads(r["company"]) if isinstance(r["company"], str) else r["company"]
                if lead:
                    lead["id"] = str(lead["id"])
                    lead["company_id"] = str(lead["company_id"])
                    lead["search_id"] = str(lead["search_id"])
                if company:
                    company["id"] = str(company["id"])
                    company["search_id"] = str(company["search_id"])
                    if isinstance(company.get("pain_points"), str):
                        company["pain_points"] = json.loads(company["pain_points"])
                drafts.append({
                    "id": str(r["id"]),
                    "lead_id": str(r["lead_id"]),
                    "subject": r["subject"],
                    "body": r["body"],
                    "status": r["status"],
                    "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"],
                    "lead": lead,
                    "company": company
                })
            return drafts

    async def log_analytics(self, user_id: str, event_type: str, event_details: Dict[str, Any]) -> None:
        """Logs an event to the analytics table."""
        id_val = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow()

        if self.use_mock:
            _mock_db["analytics"].append({
                "id": id_val,
                "user_id": user_id,
                "event_type": event_type,
                "event_details": event_details,
                "created_at": created_at.isoformat()
            })
        else:
            pool = await self.get_pool()
            await pool.execute(
                "INSERT INTO analytics (id, user_id, event_type, event_details, created_at) "
                "VALUES ($1, $2, $3, $4::jsonb, $5)",
                uuid.UUID(id_val), uuid.UUID(user_id), event_type, json.dumps(event_details), created_at
            )

    async def get_analytics_summary(self, user_id: str) -> Dict[str, Any]:
        """Gathers analytics stats for dashboard metrics."""
        if self.use_mock:
            total_searches = len(_mock_db["searches"])
            companies_found = len(_mock_db["companies"])
            saved_leads = len([l for l in _mock_db["leads"] if l["status"] in ["Draft Ready", "Contacted", "Meeting"]])
            email_drafts = len(_mock_db["email_drafts"])
            return {
                "total_searches": total_searches,
                "companies_found": companies_found,
                "saved_leads": saved_leads,
                "email_drafts": email_drafts,
                "recent_activity": sorted(
                    _mock_db["analytics"], key=lambda x: x["created_at"], reverse=True
                )[:10]
            }
        else:
            pool = await self.get_pool()
            s_count = await pool.fetchval("SELECT count(*) FROM searches") or 0
            c_count = await pool.fetchval("SELECT count(*) FROM companies") or 0
            l_count = await pool.fetchval(
                "SELECT count(*) FROM leads WHERE status IN ('Draft Ready', 'Contacted', 'Meeting')"
            ) or 0
            d_count = await pool.fetchval("SELECT count(*) FROM email_drafts") or 0
            recent_rows = await pool.fetch(
                "SELECT * FROM analytics WHERE user_id = $1 ORDER BY created_at DESC LIMIT 10",
                uuid.UUID(user_id)
            )
            recent = [
                {
                    "id": str(r["id"]),
                    "user_id": str(r["user_id"]),
                    "event_type": r["event_type"],
                    "event_details": json.loads(r["event_details"]) if isinstance(r["event_details"], str) else r["event_details"],
                    "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"]
                }
                for r in recent_rows
            ]
            return {
                "total_searches": s_count,
                "companies_found": c_count,
                "saved_leads": l_count,
                "email_drafts": d_count,
                "recent_activity": recent
            }

db = AsyncDatabase()
