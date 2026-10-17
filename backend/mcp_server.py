import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

from backend.agents.rag_service import RAGService
from backend.factory import get_chat_model

logger = logging.getLogger("mcp_server")
mcp = FastMCP("AI-Outreach-Assistant")


def clean_json(text: str) -> str:
    text = str(text).strip()

    if "```json" in text:
        text = text.split("```json", 1)[1]

    if "```" in text:
        text = text.split("```", 1)[0]

    object_start = text.find("{")
    array_start = text.find("[")

    starts = [
        position for position in [object_start, array_start]
        if position >= 0
    ]

    if not starts:
        return text

    start = min(starts)

    object_end = text.rfind("}")
    array_end = text.rfind("]")

    end = max(object_end, array_end)

    return text[start:end + 1] if end > start else text


@mcp.tool()
async def product_vector_search(
    search_id: str,
    query: str,
    limit: int = 5
) -> Dict[str, Any]:
    try:
        return await RAGService.query_product(
            search_id,
            query,
            limit=limit
        )
    except Exception as exc:
        logger.exception("Product vector search failed")
        return {
            "answer": "no",
            "tldr": str(exc),
            "sources": []
        }


@mcp.tool()
async def company_search(
    industry: str
) -> List[Dict[str, str]]:
    logger.info("AI company search for industry: %s", industry)

    try:
        llm = get_chat_model(temperature=0.2)

        prompt = f"""
Find 5 well-known real companies in the {industry} industry.

Return ONLY valid JSON:
[
  {{
    "name": "Company name",
    "domain": "official-domain.com",
    "industry": "{industry}"
  }}
]

Do not return markdown, explanations, or fictional companies.
"""

        response = await llm.ainvoke(prompt)
        results = json.loads(clean_json(response.content))

        if not isinstance(results, list):
            return []

        return [
            {
                "name": str(item["name"]),
                "domain": str(item["domain"]),
                "industry": str(item.get("industry", industry))
            }
            for item in results
            if isinstance(item, dict)
            and item.get("name")
            and item.get("domain")
        ]

    except Exception as exc:
        logger.exception("AI company search failed")
        return []


@mcp.tool()
async def company_research(
    company_name: str,
    domain: str,
    industry: Optional[str] = "Healthcare"
) -> Dict[str, Any]:
    logger.info("Researching company: %s", company_name)

    clean_domain = (
        domain.strip()
        .removeprefix("https://")
        .removeprefix("http://")
        .rstrip("/")
    )

    website = f"https://{clean_domain}"
    evidence = ""
    verified = False

    try:
        async with httpx.AsyncClient(
            timeout=12,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(compatible; AI-Outreach-Research/1.0)"
                )
            }
        ) as client:
            page = await client.get(website)
            page.raise_for_status()

        soup = BeautifulSoup(page.text, "html.parser")

        for tag in soup(
            ["script", "style", "noscript", "svg"]
        ):
            tag.decompose()

        title = (
            soup.title.get_text(" ", strip=True)
            if soup.title else ""
        )

        meta = soup.find(
            "meta",
            attrs={"name": "description"}
        )

        meta_description = (
            meta.get("content", "")
            if meta else ""
        )

        body = soup.get_text(" ", strip=True)

        evidence = " ".join(
            part for part in [
                title,
                meta_description,
                body
            ] if part
        )[:12000]

        verified = len(evidence.strip()) > 50

    except Exception as exc:
        logger.warning(
            "Website fetch failed for %s: %s",
            website,
            exc
        )

    if not evidence:
        evidence = (
            "No official website evidence was retrieved. "
            "Do not invent facts."
        )

    try:
        llm = get_chat_model(temperature=0.1)

        prompt = f"""
You are a factual B2B company researcher.

Use ONLY the official website evidence below.
Do not invent facts.
If evidence is insufficient, say so clearly.

Company: {company_name}
Domain: {domain}
Industry: {industry}

Official website evidence:
{evidence}

Return ONLY valid JSON:
{{
  "description": "A factual 2-3 sentence description",
  "pain_points": [
    "pain point supported by evidence"
  ]
}}

If the evidence is insufficient:
- description must be "Information unavailable from the official website."
- pain_points must be []
"""

        response = await llm.ainvoke(prompt)
        parsed = json.loads(clean_json(response.content))

        description = str(
            parsed.get("description", "")
        ).strip()

        pain_points = parsed.get(
            "pain_points",
            []
        )

        if not description:
            description = (
                "Information unavailable from "
                "the official website."
            )

        if not isinstance(pain_points, list):
            pain_points = []

        return {
            "company_name": company_name,
            "domain": domain,
            "industry": industry,
            "description": description,
            "pain_points": pain_points,
            "website": website,
            "source_url": website,
            "verified": verified,
            "evidence_excerpt": evidence[:4000],
            "researched_at": datetime.now(
                timezone.utc
            ).isoformat()
        }

    except Exception as exc:
        logger.exception("Company research LLM failed")

        return {
            "company_name": company_name,
            "domain": domain,
            "industry": industry,
            "description": (
                "Information unavailable from "
                "the official website."
            ),
            "pain_points": [],
            "website": website,
            "source_url": website,
            "verified": verified,
            "evidence_excerpt": evidence[:4000],
            "researched_at": datetime.now(
                timezone.utc
            ).isoformat()
        }


@mcp.tool()
async def evaluate_icp_fit(
    company_description: str,
    icp_rules: str,
    pain_points: List[str] = None
) -> Dict[str, Any]:
    try:
        llm = get_chat_model(temperature=0.1)

        prompt = f"""
Evaluate this company against the ICP.

Company evidence:
{company_description}

Pain points:
{pain_points or []}

ICP rules:
{icp_rules}

Return ONLY valid JSON:
{{
  "match_score": 85,
  "why_recommended": "Evidence-based explanation",
  "pain_points": ["relevant pain point"],
  "confidence": 80
}}

Scores and confidence must be integers from 0 to 100.
Do not invent evidence.
"""

        response = await llm.ainvoke(prompt)
        parsed = json.loads(clean_json(response.content))

        return {
            "match_score": max(
                0,
                min(100, int(parsed.get("match_score", 50)))
            ),
            "why_recommended": parsed.get(
                "why_recommended",
                "Insufficient information."
            ),
            "pain_points": parsed.get(
                "pain_points",
                pain_points or []
            ),
            "confidence": max(
                0,
                min(100, int(parsed.get("confidence", 50)))
            )
        }

    except Exception as exc:
        logger.exception("ICP evaluation failed")

        return {
            "match_score": 50,
            "why_recommended": (
                "Insufficient information for reliable scoring."
            ),
            "pain_points": pain_points or [],
            "confidence": 30
        }


@mcp.tool()
async def generate_outreach_email(
    lead_id: str
) -> Dict[str, Any]:
    from backend.agents.email_agent import draft_email_for_lead
    return await draft_email_for_lead(lead_id)