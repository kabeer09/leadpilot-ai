"""Seller profile service — single source of truth for your identity in outreach."""
from sqlalchemy.orm import Session
from app.models.seller import SellerProfile

DEFAULTS = {
    "business_name": "New Look Impex",
    "sender_name": "",
    "business_description": (
        "Manufacturer and exporter of metal urlis, metal diyas, decorative metal "
        "lanterns, festival decor, home decor, copper and brass handicrafts."
    ),
    "products": ("Metal urlis, Metal diyas, Decorative metal lanterns, Festival decor, "
                 "Home decor, Copper and brass handicrafts"),
    "country": "India",
    "city": "Moradabad",
    "website": "",
    "catalogue_url": "",
    "meeting_url": "",
}


def get_seller(db: Session) -> SellerProfile:
    """Return the seller profile, seeding defaults on first read."""
    seller = db.query(SellerProfile).filter(SellerProfile.id == 1).first()
    if not seller:
        seller = SellerProfile(id=1, **DEFAULTS)
        db.add(seller)
        db.commit()
        db.refresh(seller)
    return seller


def get_seller_dict(db: Session) -> dict:
    """Return the seller profile as the dict AI/fallback builders expect."""
    return get_seller(db).to_dict()


def update_seller(db: Session, data: dict) -> SellerProfile:
    """Update the seller profile (only known fields)."""
    seller = get_seller(db)
    allowed = set(DEFAULTS)
    for key, value in (data or {}).items():
        if key not in allowed:
            continue
        if key == "products" and isinstance(value, list):
            value = ", ".join(value)
        setattr(seller, key, value if value is not None else "")
    db.commit()
    db.refresh(seller)
    return seller
