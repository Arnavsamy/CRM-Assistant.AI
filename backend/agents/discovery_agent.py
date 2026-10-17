import sys
import asyncio
import json
import logging
from typing import List, Dict, Any, TypedDict

from langgraph.graph import StateGraph, END

from backend.database import db
from backend.config import settings

logger = logging.getLogger("discovery_agent")


class DiscoveryState(TypedDict):
    search_id: str
    user_id: str
    target_industries: List[Dict[str, Any]]
    companies_to_process: List[Dict[str, Any]]
    processed_companies: List[Dict[str, Any]]


async def call_mcp_tool(
    tool_name: str,
    **kwargs
) -> Any:
    logger.info("Calling MCP tool: %s", tool_name)

    try:
        from mcp import (
            StdioServerParameters,
            ClientSession
        )
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "backend.run_mcp"]
        )

        async with stdio_client(
            server_params
        ) as (read, write):
            async with ClientSession(
                read,
                write
            ) as session:
                await asyncio.wait_for(session.initialize(), timeout=10)

                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments=kwargs),
                    timeout=20
                )

                values = []

                for block in getattr(
                    result,
                    "content",
                    []
                ):
                    text = getattr(
                        block,
                        "text",
                        None
                    )

                    if not text:
                        continue

                    try:
                        parsed = json.loads(text)
                    except Exception:
                        continue

                    if isinstance(parsed, list):
                        values.extend(parsed)
                    else:
                        values.append(parsed)

                if tool_name == "company_search":
                    if values:
                        return values

                    # Some MCP responses may contain no readable text even
                    # though the tool call succeeded. Force the existing
                    # direct-function fallback below in that case.
                    raise RuntimeError(
                        "MCP returned no readable company results"
                    )

                return values[0] if values else {}

    except Exception as exc:
        logger.warning(
            "MCP failed; using direct function: %s",
            exc
        )

        from backend.mcp_server import (
            company_search,
            company_research,
            evaluate_icp_fit
        )

        if tool_name == "company_search":
            return await company_search(
                kwargs.get("industry", "")
            )

        if tool_name == "company_research":
            return await company_research(
                kwargs.get("company_name", ""),
                kwargs.get("domain", ""),
                kwargs.get("industry", "")
            )

        if tool_name == "evaluate_icp_fit":
            return await evaluate_icp_fit(
                kwargs.get("company_description", ""),
                kwargs.get("icp_rules", ""),
                kwargs.get("pain_points", [])
            )

        raise ValueError(
            f"Unknown MCP tool: {tool_name}"
        )


async def find_companies_node(
    state: DiscoveryState
) -> Dict[str, Any]:
    companies = []
    seen_domains = set()

    # Keep the free-tier demo responsive.  More industries/companies can be
    # added later, but an unbounded batch makes several sequential LLM calls
    # look like a hung job on sleeping free services.
    for item in state["target_industries"][:2]:
        industry = (
            item.get("industry", "")
            if isinstance(item, dict)
            else str(item)
        )

        if not industry:
            continue

        try:
            results = await call_mcp_tool(
                "company_search",
                industry=industry
            )

            for company in (results or [])[:3]:
                name = company.get("name")
                domain = company.get("domain")

                if not name or not domain:
                    continue

                domain = domain.lower().strip()

                if domain in seen_domains:
                    continue

                seen_domains.add(domain)

                companies.append({
                    "name": name,
                    "domain": domain,
                    "industry": company.get(
                        "industry",
                        industry
                    )
                })

                # Keep the first run reliably below the free-tier timeout.
                # Research and scoring are intentionally sequential for now.
                if len(companies) >= settings.DISCOVERY_COMPANY_LIMIT:
                    break

            if len(companies) >= settings.DISCOVERY_COMPANY_LIMIT:
                break

        except Exception as exc:
            logger.error(
                "Search failed for %s: %s",
                industry,
                exc
            )

    return {
        "companies_to_process": companies
    }


async def research_and_score_node(
    state: DiscoveryState
) -> Dict[str, Any]:
    search_id = state["search_id"]
    processed = []

    search = await db.get_search_details(search_id)

    icp_rules = ""

    if search:
        icp_rules = search.get(
            "icp_definition",
            {}
        ).get("icp_rules", "")

    for company in state["companies_to_process"]:
        name = company["name"]
        domain = company["domain"]
        industry = company["industry"]

        try:
            research = await call_mcp_tool(
                "company_research",
                company_name=name,
                domain=domain,
                industry=industry
            )

            description = research.get(
                "description",
                ""
            )

            pain_points = research.get(
                "pain_points",
                []
            )

            website = research.get(
                "website",
                f"https://www.{domain}"
            )

            source_url = research.get(
                "source_url",
                website
            )

            verified = bool(
                research.get("verified", False)
            )

            evidence_excerpt = research.get(
                "evidence_excerpt",
                ""
            )

            researched_at = research.get(
                "researched_at"
            )

            scoring = await call_mcp_tool(
                "evaluate_icp_fit",
                company_description=(
                    f"Description: {description}\n"
                    f"Website verified: {verified}\n"
                    f"Website evidence: "
                    f"{evidence_excerpt}"
                ),
                icp_rules=icp_rules,
                pain_points=pain_points
            )

            score = int(
                scoring.get("match_score", 50)
            )

            confidence = int(
                scoring.get("confidence", 50)
            )

            if not verified:
                score = min(score, 50)
                confidence = min(confidence, 50)
                account_status = "Needs Verification"
            else:
                account_status = "Qualified"

            stored_company = await db.insert_company(
                search_id=search_id,
                name=name,
                domain=domain,
                industry=industry,
                description=description,
                website=website,
                match_score=score,
                why_recommended=scoring.get(
                    "why_recommended",
                    "Insufficient information."
                ),
                pain_points=scoring.get(
                    "pain_points",
                    pain_points
                )
            )

            await db.save_company_evidence(
                company_id=stored_company["id"],
                source_url=source_url,
                evidence_text=evidence_excerpt,
                verified=verified
            )

            stored_company.update({
                "source_url": source_url,
                "verified": verified,
                "researched_at": researched_at,
                "evidence_excerpt": evidence_excerpt[:4000],
                "confidence": confidence,
                "status": account_status
            })

            processed.append(stored_company)

            logger.info(
                "Processed %s with score %s",
                name,
                score
            )

        except Exception as exc:
            logger.exception(
                "Error processing company %s: %s",
                name,
                exc
            )

    return {
        "processed_companies": processed
    }


def build_discovery_graph():
    builder = StateGraph(DiscoveryState)

    builder.add_node(
        "find_companies",
        find_companies_node
    )

    builder.add_node(
        "research_and_score",
        research_and_score_node
    )

    builder.set_entry_point("find_companies")

    builder.add_edge(
        "find_companies",
        "research_and_score"
    )

    builder.add_edge(
        "research_and_score",
        END
    )

    return builder.compile()


discovery_graph = build_discovery_graph()


async def run_discovery_pipeline(
    search_id: str
) -> List[Dict[str, Any]]:
    logger.info(
        "Starting discovery pipeline: %s",
        search_id
    )

    search = await db.get_search_details(search_id)

    if not search:
        raise ValueError(
            f"Search ID {search_id} not found."
        )

    result = await discovery_graph.ainvoke({
        "search_id": search_id,
        "user_id": search.get("user_id", ""),
        "target_industries": search.get(
            "target_industries",
            []
        ),
        "companies_to_process": [],
        "processed_companies": []
    })

    return result.get(
        "processed_companies",
        []
    )
