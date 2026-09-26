from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Playbook, PlaybookChecklistItem, Tag, TagCategory, User

DEFAULT_TAGS: dict[TagCategory, list[str]] = {
    TagCategory.SETUP: [
        "ORB",
        "RSI Divergence",
        "VWAP Reclaim",
        "VWAP Rejection",
        "Liquidity Sweep",
        "FVG",
        "IFVG",
        "Trend Continuation",
        "Countertrend",
    ],
    TagCategory.CONFLUENCE: [
        "Session High/Low",
        "Support",
        "Resistance",
        "200 EMA",
    ],
    TagCategory.MISTAKE: [
        "FOMO",
        "Revenge Trade",
        "Overtrading",
        "Entered Early",
        "Entered Late",
        "Moved Stop",
        "Oversized",
        "Ignored Bias",
        "No Confirmation",
        "Held Too Long",
        "Cut Winner Early",
    ],
}


def seed_default_tags(db: Session, user: User) -> None:
    existing = {
        (tag.name, tag.category)
        for tag in db.scalars(select(Tag).where(Tag.user_id == user.id)).all()
    }
    for category, names in DEFAULT_TAGS.items():
        for name in names:
            if (name, category) not in existing:
                db.add(Tag(user_id=user.id, name=name, category=category))
    db.flush()


STARTER_PLAYBOOKS = [
    (
        "ORB continuation",
        "Manual opening-range continuation plan. Confirm the range and context before use.",
        [
            "Opening range is defined",
            "Direction agrees with the session context",
            "Risk is defined",
        ],
    ),
    (
        "RSI divergence reversal",
        "Manual reversal plan using recorded divergence as one context input.",
        ["Divergence is visible", "Price confirms the reversal", "Invalidation is defined"],
    ),
    (
        "VWAP reclaim/rejection",
        "Manual plan for a confirmed VWAP reclaim or rejection.",
        ["VWAP interaction is clear", "Confirmation is present", "Stop location is defined"],
    ),
    (
        "Liquidity sweep reversal",
        "Manual plan for a sweep followed by confirmed rejection.",
        ["Reference liquidity is identified", "Sweep is complete", "Reversal confirms"],
    ),
    (
        "FVG/IFVG continuation",
        "Manual continuation plan using an FVG or IFVG as context.",
        ["Relevant gap is identified", "Continuation context is intact", "Invalidation is defined"],
    ),
]


def seed_starter_playbooks(db: Session, user: User) -> None:
    existing = {
        name
        for name in db.scalars(select(Playbook.name).where(Playbook.user_id == user.id)).all()
    }
    for name, description, checklist in STARTER_PLAYBOOKS:
        if name in existing:
            continue
        playbook = Playbook(
            user_id=user.id,
            name=name,
            description=description,
            direction_scope="both",
        )
        db.add(playbook)
        db.flush()
        for order, text in enumerate(checklist):
            db.add(
                PlaybookChecklistItem(
                    playbook_id=playbook.id,
                    text=text,
                    category="confirmation",
                    required=True,
                    sort_order=order,
                )
            )
    db.flush()
