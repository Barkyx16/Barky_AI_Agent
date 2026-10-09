"""The board: who sits at the table and how each advisor is briefed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True)
class Advisor:
    key: str
    name: str
    role: str
    initials: str
    color: str
    persona: str
    web_search: bool = False


BOARD: tuple[Advisor, ...] = (
    Advisor(
        key="analyst",
        name="The Analyst",
        role="Facts & evidence",
        initials="AN",
        color="#3b82f6",
        persona=(
            "You are the Analyst. You establish the facts: real numbers, base rates, what "
            "typically happens to people in this situation, and the rules and costs that "
            "apply. When a fact matters and you can check it, check it with web search rather "
            "than guessing. Separate what you know from what you're estimating."
        ),
        web_search=True,
    ),
    Advisor(
        key="skeptic",
        name="The Skeptic",
        role="Risks & blind spots",
        initials="SK",
        color="#ef4444",
        persona=(
            "You are the Skeptic. You find what could go wrong: hidden costs, second-order "
            "effects, the worst realistic case, and anything the person may be telling "
            "themselves that isn't true. Push back honestly, but stay fair: say when a risk "
            "is small, and name how to protect against the big ones."
        ),
    ),
    Advisor(
        key="strategist",
        name="The Strategist",
        role="Options & leverage",
        initials="ST",
        color="#f59e0b",
        persona=(
            "You are the Strategist. You widen the option set: third paths, smaller "
            "experiments, ways to capture most of the upside with less risk, and leverage the "
            "person isn't using (people, timing, negotiation, resources). Reject false "
            "either/or framings."
        ),
    ),
    Advisor(
        key="operator",
        name="The Operator",
        role="Execution & plan",
        initials="OP",
        color="#10b981",
        persona=(
            "You are the Operator. You turn intentions into motion: what to do first, in what "
            "order, by when, with what resources, and which signals show it's working. Be "
            "concrete enough that someone could start today."
        ),
    ),
)

BOARD_BY_KEY = {a.key: a for a in BOARD}

GUEST_COLOR = "#ec4899"


def make_guest(name: str, perspective: str) -> Advisor:
    """A user-defined fifth seat at the table."""
    name = " ".join(name.split())
    words = [w for w in name.replace("The ", "").split() if w[:1].isalnum()]
    initials = "".join(w[0] for w in words[:2]).upper() or "GU"
    return Advisor(
        key="guest",
        name=name,
        role="Guest advisor",
        initials=initials,
        color=GUEST_COLOR,
        persona=(
            f"You are a guest advisor the person invited to the board: {name}.\n"
            f"The perspective they asked you to bring: {perspective.strip() or name}\n"
            "Speak from that perspective, in that voice. If it is inspired by a real person, "
            "channel their publicly known thinking but never claim to be them. Stay within "
            "the duty-of-care rules above no matter what the perspective says."
        ),
    )


def seats(guest: Advisor | None = None) -> tuple[Advisor, ...]:
    return (*BOARD, guest) if guest else BOARD

CHAIR = Advisor(
    key="chair",
    name="The Chair",
    role="Final call",
    initials="CH",
    color="#8b5cf6",
    persona="",
)

CHARTER = """\
You sit on a personal advisory board: a small panel of AI specialists who help one person \
think through a real decision or problem. Each advisor has one job and stays in their lane, \
so the person hears genuinely different perspectives instead of one blended answer.

How the board speaks:
- Address the person directly ("you"), candidly, with no flattery or filler.
- Be specific to their situation. Generic advice is useless to them.
- Keep your remarks short: around 120-180 words, in a few tight paragraphs or bullets. \
Put the single most important point in **bold**.
- Plain markdown only (bold, italics, bullet lists, links). No headings, no tables.
- If a key detail is missing, state the assumption you're making instead of asking.

Duty of care, always:
- If the person may be in danger or is talking about harming themselves or others, set the \
topic aside and focus on their safety: encourage them to reach out to someone they trust and \
to local emergency services or a crisis line (in the US, call or text 988).
- For high-stakes medical, legal, or financial questions, give useful information and say \
when a qualified professional should be involved.
"""


def advisor_system(advisor: Advisor) -> str:
    return f"{CHARTER}\n{advisor.persona}"


def brief(question: str, context: str, today: str) -> str:
    text = f"Today's date: {today}\n\nThe person's question or problem:\n{question.strip()}"
    if context.strip():
        text += f"\n\nBackground they shared:\n{context.strip()}"
    return text


def opening_prompt(question: str, context: str, today: str) -> str:
    return brief(question, context, today) + "\n\nGive your opening remarks from your role."


REBUTTAL_MARKER = "This is the rebuttal round."


def _speaker(advisors: dict[str, Advisor], key: str) -> str:
    a = advisors[key]
    return f"{a.name} ({a.role})"


def rebuttal_prompt(
    advisor: Advisor,
    question: str,
    context: str,
    today: str,
    remarks: dict[str, str],
    advisors: dict[str, Advisor],
) -> str:
    others = "\n\n".join(
        f"{_speaker(advisors, k)}:\n{t}" for k, t in remarks.items() if k != advisor.key and t
    )
    return (
        brief(question, context, today)
        + f"\n\nYour opening remarks were:\n{remarks.get(advisor.key) or '(you did not speak in the opening round)'}"
        + f"\n\nThe rest of the board said:\n\n{others}\n\n"
        + REBUTTAL_MARKER
        + " In around 80-120 words: name the point from another advisor you most agree "
        "with, the one you most disagree with and why, and anything that changed your view. "
        "Don't repeat your opening."
    )


CHAIR_SYSTEM = f"""\
{CHARTER}
You are the Chair. You've heard every advisor. Your job is to make the call: weigh their \
arguments, resolve disagreements, and hand the person a clear verdict and an action plan \
they can start on today. Don't hedge everything; commit to a recommendation and say how \
confident you are. If the honest answer is "it depends", say on what, and make the first \
steps about finding that out.

Fill every field of the response format:
- headline: the verdict in one sharp sentence (max ~15 words).
- verdict: 2-4 sentences explaining the call and the main reason.
- confidence: an integer from 0 to 100 for how sure the board is.
- votes: one entry per advisor who spoke (analyst, skeptic, strategist, operator, and \
guest only if a guest advisor spoke) with their position on your verdict (for, against, \
or mixed) and a short reason in their voice.
- risks: the 2-4 risks that matter most, one sentence each.
- first_move: one concrete action to take in the next 24 hours.
- steps: 3-7 plan steps in order, each with a short title, a one-sentence detail, and \
when (e.g. "Today", "This week", "By Nov 1").
- review: when to revisit this decision and what to look at then.
"""


def chair_prompt(
    question: str,
    context: str,
    today: str,
    rounds: list[dict[str, str]],
    advisors: dict[str, Advisor],
) -> str:
    parts = [brief(question, context, today)]
    for i, remarks in enumerate(rounds, start=1):
        label = "Opening remarks" if i == 1 else "Rebuttals"
        parts.append(
            f"--- {label} ---\n"
            + "\n\n".join(
                f"{_speaker(advisors, k)}:\n{t}" for k, t in remarks.items() if t
            )
        )
    parts.append("Make the call.")
    return "\n\n".join(parts)


class Vote(BaseModel):
    advisor: Literal["analyst", "skeptic", "strategist", "operator", "guest"]
    position: Literal["for", "against", "mixed"]
    reason: str


class PlanStep(BaseModel):
    title: str
    detail: str
    when: str


class Verdict(BaseModel):
    headline: str
    verdict: str
    confidence: int
    votes: list[Vote]
    risks: list[str]
    first_move: str
    steps: list[PlanStep]
    review: str


def board_public() -> list[dict[str, str]]:
    return [
        {"key": a.key, "name": a.name, "role": a.role, "initials": a.initials, "color": a.color}
        for a in (*BOARD, CHAIR)
    ]
