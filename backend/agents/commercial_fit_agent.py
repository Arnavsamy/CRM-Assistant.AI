"""Deterministic commercial-fit estimates for the workspace agent demo."""

import math
from typing import Any, Dict

from backend.database import db


async def analyze_commercial_fit(lead_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    lead = await db.get_lead_with_company(lead_id)
    if not lead:
        raise ValueError("Lead not found")

    price = max(0.0, float(payload.get("monthly_price", 0)))
    delivery = max(0.0, float(payload.get("monthly_delivery_cost", 0)))
    months = max(1, min(120, int(payload.get("contract_months", 12))))
    discount = max(0.0, min(100.0, float(payload.get("discount_percent", 0))))
    acquisition = max(0.0, float(payload.get("acquisition_cost", 0)))
    net_monthly = price * (1 - discount / 100)
    monthly_profit = net_monthly - delivery
    margin = (monthly_profit / net_monthly * 100) if net_monthly else 0
    contract_value = net_monthly * months
    contract_profit = monthly_profit * months - acquisition
    break_even_months = math.ceil(acquisition / monthly_profit) if monthly_profit > 0 and acquisition else 0
    fit_score = float((lead.get("company") or {}).get("match_score") or 0)
    budget_multiplier = 1.5 if fit_score >= 75 else 1.15 if fit_score >= 50 else 0.85
    budget_low = net_monthly * months * budget_multiplier * 0.75
    budget_high = net_monthly * months * budget_multiplier * 1.5
    if monthly_profit <= 0:
        fit, recommendation = "Low", "Rework pricing or delivery costs before pursuing this account."
    elif contract_profit <= 0:
        fit, recommendation = "Review", "The deal may be viable, but acquisition cost or discount makes it unprofitable."
    elif fit_score >= 50:
        fit, recommendation = "Good", "Proceed with discovery and validate budget with the buyer."
    else:
        fit, recommendation = "Review", "Validate the account before investing heavily in the sales cycle."
    return {
        "lead_id": lead_id,
        "company_name": (lead.get("company") or {}).get("name") or "Lead",
        "commercial_fit": fit,
        "recommendation": recommendation,
        "assumptions": {"monthly_price": price, "monthly_delivery_cost": delivery, "contract_months": months, "discount_percent": discount, "acquisition_cost": acquisition},
        "monthly_revenue": round(net_monthly, 2),
        "monthly_gross_profit": round(monthly_profit, 2),
        "gross_margin_percent": round(margin, 1),
        "contract_value": round(contract_value, 2),
        "estimated_contract_profit": round(contract_profit, 2),
        "break_even_months": break_even_months,
        "estimated_budget_low": round(budget_low, 2),
        "estimated_budget_high": round(budget_high, 2),
        "budget_confidence": 35 if fit_score < 50 else 55 if fit_score < 75 else 70,
        "budget_basis": "Formula: contract value × ICP-fit multiplier × 0.75–1.5. This is an indicative range; confirm directly with the buyer.",
    }
