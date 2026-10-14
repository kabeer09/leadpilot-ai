"""AI email generation using local Ollama."""
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SELLER = {
    "business_name": "New Look Impex",
    "business_description": "Manufacturer and exporter of metal urlis, metal diyas, decorative metal lanterns, festival decor, home decor, copper and brass handicrafts.",
    "products": [
        "Metal urlis",
        "Metal diyas",
        "Decorative metal lanterns",
        "Festival decor",
        "Home decor",
        "Copper and brass handicrafts",
    ],
    "country": "India",
    "city": "Moradabad",
    "website": "",
    "catalogue_url": "",
    "meeting_url": "",
    "sender_name": "",
}


def _call_ollama(prompt: str) -> str | None:
    """Call Ollama API and return the response text."""
    try:
        response = httpx.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={
                "model": settings.OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        logger.error(f"Ollama call failed: {e}")
        return None


def generate_company_summary(company_data: dict) -> str | None:
    """Generate a concise company summary using AI."""
    prompt = f"""You are a B2B sales assistant. Write a concise 2-3 sentence summary of this company based ONLY on the facts provided. Do not invent any information.

Company Name: {company_data.get('company_name', 'Unknown')}
Description: {company_data.get('description', 'Not available')}
Products: {', '.join(company_data.get('products', [])) or 'Not available'}
Industry: {company_data.get('industry', 'Not available')}
Country: {company_data.get('country', 'Not available')}

Summary:"""

    return _call_ollama(prompt)


def generate_lead_score_explanation(company_data: dict, score: int, reasons: list[str]) -> str | None:
    """Generate an AI explanation for the lead score."""
    prompt = f"""You are a B2B sales assistant. Explain why this lead received a score of {score}/100 based on the following facts. Be concise and factual.

Company: {company_data.get('company_name', 'Unknown')}
Score Reasons: {', '.join(reasons)}
Products: {', '.join(company_data.get('products', [])) or 'Not available'}
Country: {company_data.get('country', 'Not available')}

Explanation (2-3 sentences):"""

    return _call_ollama(prompt)


def generate_email(company_data: dict, seller: dict | None = None) -> dict | None:
    """Generate a personalized B2B first-contact email."""
    seller = seller or DEFAULT_SELLER

    prompt = f"""You are a professional B2B sales assistant. Write a concise, professional first-contact email to this company.

COMPANY INFORMATION (from database):
- Name: {company_data.get('company_name', 'Unknown')}
- Description: {company_data.get('description', 'Not available')}
- Products: {', '.join(company_data.get('products', [])) or 'Not available'}
- Industry: {company_data.get('industry', 'Not available')}
- Country: {company_data.get('country', 'Not available')}

SELLER INFORMATION (from settings):
- Business Name: {seller.get('business_name', '')}
- Business Description: {seller.get('business_description', '')}
- Products: {', '.join(seller.get('products', []))}
- Country: {seller.get('country', '')}
- City: {seller.get('city', '')}

RULES:
1. Be concise and professional (max 150 words in body).
2. Mention relevant factual company/product context.
3. Introduce the seller naturally.
4. Offer catalogue/product discussion.
5. Offer a 1-to-1 Google Meet if interested.
6. Do NOT claim "we noticed you need our products" — use "if relevant to your sourcing or product range".
7. Do NOT claim "we have been following your company" unless explicitly true.
8. Do NOT invent any facts not provided above.
9. Do NOT use placeholders like [Company Name] or [Your Name].
10. Include a clear call-to-action.

Output format:
SUBJECT: <email subject line>
BODY:
<email body>

Email:"""

    response = _call_ollama(prompt)
    if not response:
        return None

    lines = response.split("\n")
    subject = None
    body_lines = []
    in_body = False

    for line in lines:
        if line.startswith("SUBJECT:"):
            subject = line.replace("SUBJECT:", "").strip()
        elif line.startswith("BODY:"):
            in_body = True
        elif in_body:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()

    if not subject or not body:
        return None

    return {"subject": subject, "body": body}


def generate_whatsapp_followup(company_data: dict, seller: dict | None = None) -> str | None:
    """Generate a WhatsApp follow-up message."""
    seller = seller or DEFAULT_SELLER

    prompt = f"""Write a short, professional WhatsApp follow-up message (max 80 words) for this company.

Company: {company_data.get('company_name', 'Unknown')}
Seller: {seller.get('business_name', '')}

RULES:
1. Keep it short and professional.
2. Reference the email sent previously.
3. Offer a 1-to-1 Google Meet.
4. Do NOT claim they requested a meeting.
5. Do NOT invent facts.

Message:"""

    return _call_ollama(prompt)


def classify_reply(reply_text: str) -> str:
    """Classify a reply into categories."""
    prompt = f"""Classify this email reply into exactly one category. Respond with ONLY the category name, nothing else.

Categories: INTERESTED, QUESTION, NEGOTIATION, MEETING_REQUEST, NOT_INTERESTED, UNSUBSCRIBE, OUT_OF_OFFICE, UNKNOWN

Reply:
{reply_text[:1000]}

Category:"""

    result = _call_ollama(prompt)
    if not result:
        return "UNKNOWN"

    result = result.strip().upper()
    valid_categories = [
        "INTERESTED", "QUESTION", "NEGOTIATION", "MEETING_REQUEST",
        "NOT_INTERESTED", "UNSUBSCRIBE", "OUT_OF_OFFICE", "UNKNOWN",
    ]
    return result if result in valid_categories else "UNKNOWN"
