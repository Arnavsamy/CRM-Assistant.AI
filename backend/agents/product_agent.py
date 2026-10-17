import json
import logging
from typing import List, Dict, Any, TypedDict

from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END

from backend.factory import get_chat_model
from backend.database import db

logger = logging.getLogger("product_agent")


class IndustryJustification(BaseModel):
    industry: str
    justification: str


class ProductAnalysisResult(BaseModel):
    capabilities: List[str]
    value_propositions: List[str]
    target_industries: List[IndustryJustification]
    icp_rules: str


class AgentState(TypedDict):
    product_name: str
    product_description: str
    analysis: Dict[str, Any]


def clean_json(text: str) -> str:
    text = str(text).strip()

    if "```json" in text:
        text = text.split("```json", 1)[1]

    if "```" in text:
        text = text.split("```", 1)[0]

    start = text.find("{")
    end = text.rfind("}")

    if start >= 0 and end > start:
        return text[start:end + 1]

    return text


def fallback_analysis(
    product_name: str,
    product_description: str
) -> Dict[str, Any]:
    return {
        "capabilities": [product_name],
        "value_propositions": [
            "Reduce manual work",
            "Improve operational efficiency"
        ],
        "target_industries": [
            {
                "industry": "Technology",
                "justification": (
                    "Technology companies commonly adopt software "
                    "and AI tools."
                )
            },
            {
                "industry": "Healthcare",
                "justification": (
                    "Healthcare organizations often need "
                    "workflow and support automation."
                )
            }
        ],
        "icp_rules": (
            f"Companies that could benefit from {product_name}. "
            f"Product context: {product_description}"
        )
    }


async def analyze_product_node(
    state: AgentState
) -> Dict[str, Any]:
    product_name = state["product_name"]
    product_description = state["product_description"]

    logger.info("Analyzing product: %s", product_name)

    prompt = f"""
You are an expert B2B product and ICP strategist.

Analyze this product:

Product name:
{product_name}

Product description:
{product_description}

Return ONLY valid JSON using exactly this structure:

{{
  "capabilities": ["maximum 5 short items"],
  "value_propositions": ["maximum 4 short items"],
  "target_industries": [
    {{
      "industry": "industry name",
      "justification": "one short sentence"
    }}
  ],
  "icp_rules": "one concise paragraph describing ideal companies"
}}

Rules:
- Return maximum 5 capabilities.
- Return maximum 4 value propositions.
- Return maximum 3 target industries.
- Do not use markdown.
- Do not add extra keys.
- Do not leave any field empty.
"""

    try:
        llm = get_chat_model(temperature=0.0)
        response = await llm.ainvoke(prompt)

        content = clean_json(response.content)
        parsed = json.loads(content)

        validated = ProductAnalysisResult.model_validate(parsed)

        return {
            "analysis": validated.model_dump()
        }

    except Exception as exc:
        logger.exception(
            "Product analysis failed; using safe fallback: %s",
            exc
        )

        return {
            "analysis": fallback_analysis(
                product_name,
                product_description
            )
        }


def build_product_graph():
    builder = StateGraph(AgentState)

    builder.add_node(
        "analyze_product",
        analyze_product_node
    )

    builder.set_entry_point("analyze_product")

    builder.add_edge(
        "analyze_product",
        END
    )

    return builder.compile()


product_graph = build_product_graph()


async def run_product_pipeline(
    search_id: str,
    product_name: str,
    product_description: str
) -> Dict[str, Any]:
    logger.info("Executing product analysis LangGraph flow.")

    result = await product_graph.ainvoke({
        "product_name": product_name,
        "product_description": product_description,
        "analysis": {}
    })

    analysis = result["analysis"]

    icp_definition = {
        "capabilities": analysis["capabilities"],
        "value_propositions": analysis["value_propositions"],
        "icp_rules": analysis["icp_rules"]
    }

    await db.update_search_icp(
        search_id,
        icp_definition,
        analysis["target_industries"]
    )

    return analysis