import json
import logging
from typing import Dict, Any

# Import local modules
from backend.database import db
from backend.factory import get_chat_model
from backend.agents.rag_service import RAGService

logger = logging.getLogger("email_agent")

async def draft_email_for_lead(lead_id: str) -> Dict[str, Any]:
    """
    Generates a personalized outreach email draft for a lead using
    Product capabilities, ICP rules, researched company details, and pain points.
    """
    logger.info(f"Generating personalized email draft for lead {lead_id}...")
    
    # 1. Fetch Lead Details from PostgreSQL.
    lead = await db.get_lead_with_company(lead_id)
        
    if not lead or not lead.get("company"):
        raise ValueError(f"Lead {lead_id} or associated company not found.")
        
    company = lead["company"]
    search_id = lead["search_id"]
    company_name = company["name"]
    company_desc = company["description"]
    company_industry = company["industry"]
    pain_points = company.get("pain_points", [])
    
    # 2. Fetch Product Search/ICP Profile
    search_details = await db.get_search_details(search_id)
    product_name = search_details.get("product_name", "Our Product")
    product_desc = search_details.get("product_description", "")
    icp_definition = search_details.get("icp_definition", {})
    icp_rules = icp_definition.get("icp_rules", "")
    
    # 3. Retrieve Product RAG context matching company's pain points
    product_context = ""
    try:
        query_text = " ".join(pain_points) if pain_points else company_desc
        rag_result = await RAGService.query_product(search_id, query_text, limit=3)
        if rag_result["answer"] == "yes":
            product_context = "\n".join(item["content"] for item in rag_result["sources"])
    except Exception as e:
        logger.warning(f"Failed to retrieve Product RAG context: {e}")
        product_context = f"Product Description: {product_desc}"
        
    # 4. Assemble the personalization prompt for the LLM
    llm = get_chat_model(temperature=0.3)
    
    prompt = (
        f"You are a Principal Outbound Sales Copywriter.\n"
        f"Generate a highly personalized, compelling cold outreach email to a prospect company.\n\n"
        f"Product Details:\n"
        f"- Product Name: {product_name}\n"
        f"- Matching Capabilities / RAG Context:\n{product_context}\n\n"
        f"Prospect Company Details:\n"
        f"- Company Name: {company_name}\n"
        f"- Industry: {company_industry}\n"
        f"- Description: {company_desc}\n"
        f"- Key Pain Points: {pain_points}\n\n"
        f"Email Copywriting Guidelines:\n"
        f"1. Subject line should be relevant, interesting, and brief (under 8 words).\n"
        f"2. Reference the prospect's specific pain points and clearly map them to {product_name}'s value proposition.\n"
        f"3. Include a very low-friction Call to Action (CTA) asking for a quick reply or brief chat.\n"
        f"4. Keep the entire email concise, warm, professional, and under 100 words.\n"
        f"5. Do NOT use placeholders. Generate a complete, ready-to-send draft.\n\n"
        f"Output a JSON object ONLY with the following structure:\n"
        f"{{\n"
        f"  \"subject\": \"Prospect email subject line\",\n"
        f"  \"body\": \"Prospect email body text\"\n"
        f"}}\n"
        f"Do not return any markdown code blocks or extra text. Return valid JSON."
    )
    
    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()
        
        # Clean markdown code block wraps
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        parsed = json.loads(content)
        subject = parsed.get("subject", f"Quick question regarding {company_industry} operations")
        body = parsed.get("body", f"Hi,\n\nI noticed that {company_name} is scaling operations. {product_name} helps automate manual tasks. Let me know if you are open to a brief chat.\n\nBest regards.")
    except Exception as e:
        logger.error(f"Error calling LLM for email generation: {e}. Using structural fallback.")
        subject = f"Improving {company_industry} efficiency with {product_name}"
        body = (
            f"Hi,\n\nI researched {company_name} and noticed your focus on {company_industry} services. "
            f"Given your likely pain points around: {', '.join(pain_points[:2]) if pain_points else 'operational bottlenecks'}, "
            f"I wanted to share how {product_name} can help automate incoming flows and reduce manual overhead.\n\n"
            f"Are you open to a brief 5-minute call this week?\n\n"
            f"Best regards,\nOutreach Team"
        )
        
    # 5. Persist the generated draft in database
    draft = await db.create_email_draft(lead_id, subject, body)
    
    # 6. Automatically update lead status to 'Draft Ready' inside database
    await db.update_lead_status(lead_id, "Draft Ready")
    
    return {
        "status": "success",
        "draft": draft
    }
