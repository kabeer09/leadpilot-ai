"""AI output validator — checks generated content against database facts."""
import re
import logging

logger = logging.getLogger(__name__)

PROHIBITED_PATTERNS = [
    r"\[.*?\]",
    r"\{\{.*?\}\}",
    r"TODO",
    r"FIXME",
    r"XXX",
    r"lorem ipsum",
]

UNSUPPORTED_CLAIM_PATTERNS = [
    r"we noticed you need",
    r"we have been following your company",
    r"we know you are looking for",
    r"you recently inquired",
    r"you requested",
    r"your order",
    r"your budget",
    r"your partnership",
    r"your certification",
    r"your award",
]


class ValidationResult:
    """Result of AI output validation."""

    def __init__(self, is_valid: bool, errors: list[str], warnings: list[str]):
        self.is_valid = is_valid
        self.errors = errors
        self.warnings = warnings

    def to_dict(self):
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def validate_email(subject: str | None, body: str | None, company_data: dict, seller_data: dict | None = None) -> ValidationResult:
    """Validate AI-generated email against database facts and business rules."""
    errors = []
    warnings = []

    if not subject or len(subject.strip()) < 3:
        errors.append("Email subject is missing or too short")

    if not body or len(body.strip()) < 20:
        errors.append("Email body is missing or too short")

    if body and len(body) > 2000:
        warnings.append("Email body is very long (>2000 chars)")

    combined = f"{subject or ''} {body or ''}"
    for pattern in PROHIBITED_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            errors.append(f"Prohibited pattern found: {pattern}")

    for pattern in UNSUPPORTED_CLAIM_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            errors.append(f"Unsupported claim detected: '{pattern}'")

    company_name = company_data.get("company_name", "")
    if company_name and company_name.lower() not in combined.lower():
        warnings.append(f"Company name '{company_name}' not found in email")

    cta_patterns = [
        r"let me know", r"please let us know", r"happy to",
        r"would you like", r"shall we", r"can we schedule",
        r"google meet", r"call", r"meeting", r"connect",
    ]
    has_cta = any(re.search(p, combined, re.IGNORECASE) for p in cta_patterns)
    if not has_cta:
        warnings.append("No clear call-to-action detected")

    private_patterns = [
        r"\b\d{3}-\d{2}-\d{4}\b",
        r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
    ]
    for pattern in private_patterns:
        if re.search(pattern, combined):
            errors.append("Potential private/sensitive information detected")

    is_valid = len(errors) == 0
    return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)


def get_fallback_email(company_data: dict, seller_data: dict | None = None) -> dict:
    """Generate a safe fallback email when AI validation fails."""
    seller = seller_data or {
        "business_name": "New Look Impex",
        "business_description": "Manufacturer and exporter of metal urlis, metal diyas, decorative metal lanterns, festival decor, home decor, copper and brass handicrafts.",
        "products": ["Metal urlis", "Metal diyas", "Decorative metal lanterns", "Festival decor", "Home decor", "Copper and brass handicrafts"],
        "country": "India",
        "city": "Moradabad",
    }

    company_name = company_data.get("company_name", "your company")
    products = company_data.get("products", [])
    products_text = ", ".join(products[:5]) if products else "your products"

    subject = f"Exploring {products_text} — {seller['business_name']}"

    body = f"""Dear {company_name} Team,

I hope this message finds you well. My name is {seller.get('sender_name', 'the sales team')} from {seller['business_name']}, based in {seller.get('city', '')}, {seller.get('country', '')}.

We are a {seller['business_description']}

If relevant to your sourcing or product range, we would be happy to share our catalogue and discuss how we might work together.

Would you be open to a short 1-to-1 Google Meet to explore this further?

Best regards,
{seller.get('sender_name', seller['business_name'])}
{seller['business_name']}
"""

    return {"subject": subject, "body": body}


def get_fallback_whatsapp(company_data: dict, seller_data: dict | None = None) -> str:
    """Generate a safe fallback WhatsApp follow-up when AI is unavailable."""
    seller = seller_data or {"business_name": "New Look Impex"}

    company_name = company_data.get("company_name", "your company")

    return (
        f"Hello {company_name} team, this is {seller['business_name']}. "
        f"We emailed you yesterday about our metal decor range and catalogue. "
        f"If relevant to your sourcing, would you be open to a short 1-to-1 "
        f"Google Meet? Reply STOP to opt out."
    )


def evaluate_contact_email(email: str | None, company_data: dict) -> dict:
    """AI-evaluate whether a contact email plausibly belongs to a company.

    Deterministic base score from domain evidence, refined by Ollama when
    available (AI can only adjust within ±15 and never overrides a hard
    domain match/mismatch — rules stay authoritative for safety).

    Returns {"score": 0-100, "verdict": valid|suspicious|invalid,
             "reason": str, "method": "ai+rules"|"rules"}.
    """
    from app.services.contact_validation import check_email_match, domain_of

    website = company_data.get("website")
    company_name = company_data.get("company_name", "the company") or "the company"

    if not email or "@" not in email:
        return {"score": 0, "verdict": "invalid",
                "reason": "No email address to evaluate.", "method": "rules"}

    check = check_email_match(email, website)
    domain = domain_of(email)
    if check["reason"] == "domain_match":
        base, verdict = 90, "valid"
        reason = f"Email domain matches the company website ({domain})."
    elif check["reason"] == "domain_match_sld":
        base, verdict = 75, "valid"
        reason = f"Same company name with a different country domain ({domain})."
    elif check["reason"] == "free_provider":
        base, verdict = 25, "suspicious"
        reason = (f"Free-mailbox address ({domain}) — cannot prove it belongs "
                  f"to {company_name}; confirm before bulk sending.")
    elif check["reason"] == "no_website":
        base, verdict = 50, "suspicious"
        reason = (f"No company website on record to check {domain} against; "
                  f"treat as unverified.")
    else:  # domain_mismatch
        base, verdict = 35, "suspicious"
        reason = (f"Email domain ({domain}) differs from the company website; "
                  f"it may be a sister brand, old domain, or wrong address.")

    # Company-name hint in the local part adds confidence
    first_token = (company_name.lower().split() or [""])[0]
    local = email.split("@")[0].lower()
    if len(first_token) >= 4 and first_token in local.replace(".", "").replace("_", ""):
        base = min(95, base + 5)
        reason += " Company name appears in the address."

    method = "rules"
    try:
        from app.services.ai_generator import _call_ollama
        prompt = (
            "You assess whether a business email belongs to a company. "
            "Reply with exactly one line: SCORE <0-100> | <one short reason>. "
            "Start from the given base score and adjust at most 15 points.\n"
            f"Company: {company_name}\n"
            f"Website: {website or 'unknown'}\n"
            f"Email: {email}\n"
            f"Base score: {base} ({reason})\n"
            "Assessment:"
        )
        raw = _call_ollama(prompt)
        if raw:
            m = re.search(r"SCORE\s*(\d{1,3})", raw.upper())
            tail = raw.split("|", 1)[1].strip() if "|" in raw else ""
            if m:
                ai_score = max(0, min(100, int(m.group(1))))
                # AI refines within ±15; rules stay authoritative
                score = max(0, min(100, base + max(-15, min(15, ai_score - base))))
                if tail:
                    reason = tail[:300]
                method = "ai+rules"
                base = score
    except Exception as e:
        logger.warning(f"Contact eval AI failed, keeping rules score: {e}")

    if base >= 70:
        verdict = "valid"
    else:
        # Never label a real-looking address outright invalid; a human
        # decides from the reason. Scores <40 stay suspicious.
        verdict = "suspicious"
    return {"score": base, "verdict": verdict, "reason": reason, "method": method}
