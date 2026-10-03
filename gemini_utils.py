"""Core AI logic for PocketSmart AI: prompt orchestration, Gemini calls,
shopping-link generation, budget validation and fallback recommendations."""
import os
import re
import json
import urllib.parse
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
from PIL import Image
from fastapi import HTTPException

from models import HomeBudgetInput, PartyBudgetInput, JewelryBudgetInput

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", "").strip() or "gemini-2.5-flash"

_client = None


def get_client():
    """Create the Gemini client lazily so the app still starts without a key."""
    global _client
    if _client is None:
        if not API_KEY:
            raise RuntimeError("No Google API key found. Set GOOGLE_API_KEY in your .env file.")
        from google import genai
        _client = genai.Client(api_key=API_KEY)
    return _client


def generate_json(contents) -> Dict[str, Any]:
    """Call Gemini (text or text+image) and parse the JSON reply."""
    from google.genai import types
    client = get_client()
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.4),
    )
    return extract_json_from_response(response.text)


def extract_json_from_response(text: str) -> Dict[str, Any]:
    """Extract a JSON object from a model reply (handles ```json fences)."""
    if not text:
        raise ValueError("Empty response from AI model")
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in AI response")
    return json.loads(cleaned[start:end + 1])


def usd_to_inr(amount_usd: float, exchange_rate: float = 83.0) -> float:
    """Convert USD amount to INR using the specified exchange rate"""
    return amount_usd * exchange_rate


# --------------------------------------------------------------------------
# Shopping links
# --------------------------------------------------------------------------
PLATFORM_URLS = {
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "ikea": "https://www.ikea.com/in/en/search/?q={q}",
    "myntra": "https://www.myntra.com/search?q={q}",
    "ajio": "https://www.ajio.com/search/?text={q}",
    "bigbasket": "https://www.bigbasket.com/ps/?q={q}",
    "swiggy": "https://www.swiggy.com/search?query={q}",
    "zomato": "https://www.zomato.com/search?q={q}",
    "bookmyshow": "https://in.bookmyshow.com/search?q={q}",
    "meesho": "https://www.meesho.com/search?q={q}",
    "google": "https://www.google.com/search?q={q}",
    "booking": "https://www.booking.com/search.html?ss={q}",
    "makemytrip": "https://www.makemytrip.com/hotels/hotel-listing/?searchText={q}",
    "oyorooms": "https://www.oyorooms.com/search/?location={q}",
    "nobroker": "https://www.nobroker.in/property/search?searchTerm={q}",
    "bluestone": "https://www.bluestone.com/search.html?query={q}",
    "tanishq": "https://www.tanishq.co.in/search?q={q}",
    "caratlane": "https://www.caratlane.com/search?q={q}",
    "melorra": "https://www.melorra.com/search?q={q}",
}

HOME_PLATFORMS = ["amazon", "flipkart", "ikea", "myntra", "ajio"]
JEWELRY_PLATFORMS = ["amazon", "flipkart", "bluestone", "tanishq", "caratlane", "melorra", "meesho"]
VENUE_PLATFORMS = ["google", "booking", "makemytrip", "oyorooms", "nobroker"]

CATEGORY_PLATFORMS = {
    "venue": ["google", "booking", "makemytrip", "oyorooms", "nobroker"],
    "catering": ["swiggy", "zomato"],
    "food": ["swiggy", "zomato", "bigbasket", "amazon", "flipkart"],
    "drinks": ["swiggy", "zomato", "bigbasket", "amazon", "flipkart"],
    "decoration": ["amazon", "flipkart", "meesho", "myntra"],
    "entertainment": ["bookmyshow", "amazon", "flipkart"],
    "gifts": ["amazon", "flipkart", "myntra", "meesho"],
    "photography": ["google", "amazon", "flipkart"],
    "music": ["amazon", "flipkart", "bookmyshow"],
    "games": ["amazon", "flipkart"],
    "accessories": ["amazon", "flipkart", "myntra", "meesho"],
    "transportation": ["makemytrip", "google"],
    "return_gifts": ["amazon", "flipkart", "myntra", "meesho"],
}
DEFAULT_PLATFORMS = ["amazon", "flipkart", "google"]


def build_links(platforms: List[str], terms: str) -> Dict[str, str]:
    q = urllib.parse.quote_plus(terms)
    return {p: PLATFORM_URLS[p].format(q=q) for p in platforms if p in PLATFORM_URLS}


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# HOME
# --------------------------------------------------------------------------
def _home_prompt(b: HomeBudgetInput) -> str:
    return f"""
I need interior design product recommendations for a home in India with a total budget of ₹{b.total_budget:.2f}.
Requirements:
- {b.num_lights} lights/lighting fixtures
- {b.num_fans} ceiling fans
- {b.num_furniture} furniture pieces
- {b.num_dining_tables} dining tables

Additional rooms to consider:
{"- Living room" if b.has_living_room else ""}
{"- Kitchen" if b.has_kitchen else ""}
{"- Bedroom" if b.has_bedroom else ""}

Additional requirements: {b.additional_requirements or "None"}

Please provide a detailed budget breakdown with product recommendations **available in India**.
Use **Indian brands and pricing** (INR). Include **search terms** suitable for Indian shopping platforms.
"estimated_price" is the price of ONE unit; the cost of an item is estimated_price x quantity.
Use the categories "lighting", "ceiling_fans", "furniture", "dining_tables" (only those with quantity > 0).

Format your response as JSON with the following structure:
{{
  "total_budget": {b.total_budget:.2f},
  "budget_breakdown": [
    {{
      "category": "lighting",
      "allocation": 0.0,
      "items": [
        {{"name": "", "description": "", "estimated_price": 0.0, "quantity": 0, "search_terms": ""}}
      ]
    }}
  ],
  "additional_suggestions": []
}}

Ensure total costs stay within budget. Include search terms for each item to find on shopping websites
like Flipkart, Amazon India, IKEA India.
"""


def _finalize_home(result: Dict[str, Any], b: HomeBudgetInput) -> Dict[str, Any]:
    """Recompute totals in code (never trust model arithmetic) and add shopping links."""
    spent_total = 0.0
    table = []
    for cat in result.get("budget_breakdown", []):
        cat_total, count = 0.0, 0
        for item in cat.get("items", []):
            price, qty = _num(item.get("estimated_price")), int(_num(item.get("quantity"), 1)) or 1
            item["estimated_price"], item["quantity"] = price, qty
            cat_total += price * qty
            count += qty
            terms = item.get("search_terms") or item.get("name", "")
            if terms:
                item["shopping_links"] = build_links(HOME_PLATFORMS, terms)
        cat["allocation"] = round(cat_total, 2)
        spent_total += cat_total
        table.append({"category": cat.get("category", ""), "items_count": count,
                      "total_cost": round(cat_total, 2),
                      "percentage_of_budget": round(cat_total / b.total_budget * 100, 1)})
    if spent_total > b.total_budget:
        raise ValueError("AI plan exceeded the budget")
    result["total_budget"] = b.total_budget
    result["calculation_table"] = table
    result["remaining_budget"] = round(b.total_budget - spent_total, 2)
    result.setdefault("additional_suggestions", [])
    return result


def _home_fallback(b: HomeBudgetInput, reason: str) -> Dict[str, Any]:
    wanted = [
        ("lighting", "LED Light Fixture", "Energy-efficient LED fixture for general lighting.", b.num_lights, 0.20, "LED light fixture"),
        ("ceiling_fans", "Ceiling Fan (Energy Saving)", "Basic, functional BLDC/standard ceiling fan.", b.num_fans, 0.30, "ceiling fan 1200mm"),
        ("furniture", "Furniture Piece", "Simple, durable furniture piece (chair/side table).", b.num_furniture, 0.30, "home furniture chair"),
        ("dining_tables", "Dining Table", "Compact dining table with sturdy finish.", b.num_dining_tables, 0.20, "dining table"),
    ]
    wanted = [w for w in wanted if w[3] > 0]
    weight = sum(w[4] for w in wanted) or 1
    breakdown = []
    for cat, name, desc, qty, w, terms in wanted:
        alloc = b.total_budget * 0.9 * (w / weight)
        breakdown.append({"category": cat, "allocation": alloc, "items": [{
            "name": name, "description": desc, "estimated_price": round(alloc / qty, 2),
            "quantity": qty, "search_terms": terms}]})
    result = {"total_budget": b.total_budget, "budget_breakdown": breakdown,
              "additional_suggestions": [
                  reason,
                  "Look for sales and discounts on online marketplaces.",
                  "Prioritize essential items and postpone non-essential purchases."],
              "source": "fallback"}
    return _finalize_home(result, b)


def get_home_recommendations(budget_input: HomeBudgetInput) -> dict:
    """Generate home interior recommendations within budget in INR for Indian market"""
    try:
        try:
            result = _finalize_home(generate_json(_home_prompt(budget_input)), budget_input)
            result["source"] = "gemini"
            return result
        except Exception as e:  # Activity 5.4 - fallback when AI fails/exceeds budget
            print(f"[home] Gemini failed, using fallback ({type(e).__name__}).")
            return _home_fallback(budget_input, "Showing standard recommendations because the AI service was unavailable.")
    except Exception as e:
        raise HTTPException(500, f"Error generating recommendations: {str(e)}")


# --------------------------------------------------------------------------
# PARTY
# --------------------------------------------------------------------------
def _party_prompt(b: PartyBudgetInput) -> str:
    return f"""
I need party planning recommendations for India with a total budget of ₹{b.total_budget:.2f}.

Party details:
- Type: {b.party_type}
- Number of guests: {b.num_guests}
- Venue type: {b.venue_type or "Not specified"}
- Catering needed: {"Yes" if b.needs_catering else "No"}
- Decoration needed: {"Yes" if b.needs_decoration else "No"}
- Entertainment needed: {"Yes" if b.needs_entertainment else "No"}

Additional requirements: {b.additional_requirements or "None"}

Please provide a detailed budget breakdown with specific recommendations available in India using INR prices.
Use Indian brands, services, and typical cost expectations.
Use these lowercase categories: "venue", "catering", "decoration", "entertainment", "contingency"
(only include catering/decoration/entertainment when needed). "estimated_price" of an item is its TOTAL cost.

Format your response as JSON with the following structure:
{{
  "total_budget": {b.total_budget:.2f},
  "budget_breakdown": [
    {{
      "category": "venue",
      "allocation": 0.0,
      "items": [
        {{"name": "", "description": "", "estimated_price": 0.0, "quantity": 0, "search_terms": ""}}
      ]
    }}
  ],
  "venue_suggestions": [
    {{"name": "", "type": "", "capacity": 0, "estimated_cost": 0.0, "search_terms": ""}}
  ],
  "additional_suggestions": []
}}

Ensure all costs are in INR and total does not exceed the given budget.
Provide search terms suitable for Indian websites such as BookMyShow, Swiggy, Flipkart, etc.
"""


def _finalize_party(result: Dict[str, Any], b: PartyBudgetInput) -> Dict[str, Any]:
    categories: Dict[str, Dict[str, Any]] = {}
    spent = 0.0
    for category in result.get("budget_breakdown", []):
        cat_name = category.get("category", "Misc")
        cat_key = cat_name.lower()
        relevant = CATEGORY_PLATFORMS.get(cat_key, DEFAULT_PLATFORMS)
        total = 0.0
        for item in category.get("items", []):
            item["estimated_price"] = _num(item.get("estimated_price"))
            total += item["estimated_price"]
            terms = item.get("search_terms") or item.get("name", "")
            if terms:
                item["shopping_links"] = build_links(relevant, terms)
        category["allocation"] = round(total, 2)
        spent += total
        categories[cat_name] = {"category": cat_name, "items_count": len(category.get("items", [])),
                                "total_cost": round(total, 2),
                                "percentage_of_budget": round(total / b.total_budget * 100, 1)}
    if spent > b.total_budget:
        raise ValueError("AI plan exceeded the budget")
    for venue in result.get("venue_suggestions", []):
        terms = venue.get("search_terms") or venue.get("name", "")
        if terms:
            venue["search_links"] = build_links(VENUE_PLATFORMS, terms)
    result["total_budget"] = b.total_budget
    result["calculation_table_inr"] = list(categories.values())
    result["remaining_budget"] = round(b.total_budget - spent, 2)
    result.setdefault("venue_suggestions", [])
    result.setdefault("additional_suggestions", [])
    return result


def _party_fallback(b: PartyBudgetInput, reason: str) -> Dict[str, Any]:
    at_home = (b.venue_type or "").lower() in ("home", "house")
    plan = [("venue", "Venue", f"{b.venue_type or 'Venue'} for {b.num_guests} guests",
             0.0 if at_home else 0.25, f"{b.venue_type or 'party hall'} for {b.party_type}")]
    if b.needs_catering:
        plan.append(("catering", "Catering", f"Meals for {b.num_guests} guests", 0.40, f"{b.party_type} party catering"))
    if b.needs_decoration:
        plan.append(("decoration", "Decoration kit", f"{b.party_type} decoration set", 0.15, f"{b.party_type} party decoration"))
    if b.needs_entertainment:
        plan.append(("entertainment", "Entertainment", "Music, games and activities", 0.10, "party games speaker"))
    plan.append(("contingency", "Unexpected expenses", "Buffer for unforeseen costs", 0.10, "party supplies"))
    breakdown = [{"category": c, "allocation": b.total_budget * w, "items": [{
        "name": n, "description": d, "estimated_price": round(b.total_budget * w, 2),
        "quantity": 1, "search_terms": t}]} for c, n, d, w, t in plan]
    venues = [] if not at_home else [{"name": "Home", "type": "Residential", "capacity": b.num_guests,
                                      "estimated_cost": 0.0, "search_terms": ""}]
    result = {"total_budget": b.total_budget, "budget_breakdown": breakdown, "venue_suggestions": venues,
              "additional_suggestions": [reason,
                                         "Consider a potluck style meal to reduce catering costs.",
                                         "Homemade decorations can be a cost-effective alternative."],
              "source": "fallback"}
    return _finalize_party(result, b)


def get_party_recommendations(budget_input: PartyBudgetInput) -> dict:
    """Generate party planning recommendations within budget in INR for Indian market"""
    try:
        try:
            result = _finalize_party(generate_json(_party_prompt(budget_input)), budget_input)
            result["source"] = "gemini"
            return result
        except Exception as e:
            print(f"[party] Gemini failed, using fallback ({type(e).__name__}).")
            return _party_fallback(budget_input, "Showing standard recommendations because the AI service was unavailable.")
    except Exception as e:
        raise HTTPException(500, f"Error generating recommendations: {str(e)}")


# --------------------------------------------------------------------------
# JEWELRY
# --------------------------------------------------------------------------
def _jewelry_prompt(b: JewelryBudgetInput, with_image: bool) -> str:
    base = f"""
I need jewelry recommendations for India with a total budget of ₹{b.total_budget:.2f}.

Occasion: {b.occasion}
Preferences: {b.preferences or "Not specified"}
Provide only India-relevant styles, availability, and price ranges in INR.
"""
    outfit_block = ""
    outfit_json = ""
    if with_image:
        base += """
An image of the outfit is uploaded. Suggest jewelry that complements it, considering color, design, and occasion appropriateness.
"""
        outfit_block = ""
        outfit_json = '"outfit_analysis": {"colors": [], "style": "", "formality": ""},\n  '
    return base + f"""
Format the output as JSON:
{{
  {outfit_json}"total_budget": {b.total_budget:.2f},
  "jewelry_recommendations": [
    {{"item_type": "", "description": "", "style": "", "estimated_price": 0.0, "search_terms": ""}}
  ],
  "styling_tips": []
}}

Make sure prices are in INR and stay within budget. Keep prices relevant to Indian brands.
Include Indian-friendly search terms for shopping.
{outfit_block}"""


def _finalize_jewelry(result: Dict[str, Any], b: JewelryBudgetInput) -> Dict[str, Any]:
    spent = 0.0
    for item in result.get("jewelry_recommendations", []):
        item["estimated_price"] = _num(item.get("estimated_price"))
        spent += item["estimated_price"]
        terms = item.get("search_terms") or item.get("item_type", "")
        if terms:
            item["shopping_links"] = build_links(JEWELRY_PLATFORMS, terms)
    if spent > b.total_budget:
        raise ValueError("AI plan exceeded the budget")
    result["total_budget"] = b.total_budget
    result["remaining_budget"] = round(b.total_budget - spent, 2)
    result.setdefault("styling_tips", [])
    return result


def _jewelry_fallback(b: JewelryBudgetInput, reason: str) -> Dict[str, Any]:
    plan = [("necklace", "Elegant necklace suited to the occasion", 0.40, "necklace for women"),
            ("earrings", "Matching earrings", 0.25, "earrings for women"),
            ("bracelet", "Simple bracelet or bangles", 0.20, "bracelet for women"),
            ("ring", "Minimalist ring", 0.10, "ring for women")]
    recs = [{"item_type": t, "description": d, "style": b.preferences or "classic",
             "estimated_price": round(b.total_budget * w, 2), "search_terms": f"{s} {b.occasion}"}
            for t, d, w, s in plan]
    result = {"total_budget": b.total_budget, "jewelry_recommendations": recs,
              "styling_tips": [reason, "Keep metal tones consistent across pieces.",
                               "Pick one statement piece and keep the rest minimal."],
              "source": "fallback"}
    return _finalize_jewelry(result, b)


def get_jewelry_recommendations(budget_input: JewelryBudgetInput, image_path: Optional[str] = None) -> dict:
    """Generate jewelry recommendations based on uploaded dress and budget in INR (India-specific)"""
    try:
        try:
            if image_path:
                img = Image.open(image_path)
                img.load()
                contents = [_jewelry_prompt(budget_input, True), img]
            else:
                contents = _jewelry_prompt(budget_input, False)
            result = _finalize_jewelry(generate_json(contents), budget_input)
            result["source"] = "gemini"
            return result
        except Exception as e:
            print(f"[jewelry] Gemini failed, using fallback ({type(e).__name__}).")
            return _jewelry_fallback(budget_input, "Showing standard recommendations because the AI service was unavailable.")
    except Exception as e:
        raise HTTPException(500, f"Error generating recommendations: {str(e)}")
