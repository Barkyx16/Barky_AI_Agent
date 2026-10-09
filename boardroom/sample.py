"""A hand-written example meeting shown to visitors before they sign up."""

SAMPLE_MEETING = {
    "question": "Should I leave my corporate marketing job to open a coffee shop?",
    "mode": "deep",
    "created_at": None,
    "guest": None,
    "takes": [
        {
            "member": "analyst",
            "round": 1,
            "sources": [],
            "text": (
                "Independent cafés are a tough business on the numbers. Build-out for a small shop "
                "commonly runs **$150k–$400k**, net margins for those that survive are often in the "
                "**5–10%** range, and many owners don't pay themselves a market salary for the first "
                "two years.\n\n"
                "What decides this for you specifically:\n"
                "- **Runway:** how many months you can cover personal costs with zero income\n"
                "- **Location economics:** rent as a share of projected sales (under ~10% is healthy)\n"
                "- **Your edge:** what you bring besides loving coffee — operations, a following, a site\n\n"
                "Your marketing background is a genuine asset: customer acquisition is where many "
                "first-time owners struggle."
            ),
        },
        {
            "member": "skeptic",
            "round": 1,
            "sources": [],
            "text": (
                "Let me push on the fantasy. Running a café is mostly **staffing, inventory, and "
                "5:30am opens**, not crafting lattes for regulars. Ask yourself honestly whether you "
                "want the *job* or the *idea* of it.\n\n"
                "Specific risks:\n"
                "- A personal guarantee on a 5–10 year lease can follow you even if the shop closes\n"
                "- Your savings become the business's buffer, and your family's safety net shrinks\n"
                "- Burnout: owners commonly work 60+ hour weeks in year one\n\n"
                "None of this means no. It means **don't sign a lease until you've stress-tested the "
                "daily reality.**"
            ),
        },
        {
            "member": "strategist",
            "round": 1,
            "sources": [],
            "text": (
                "This isn't quit-or-stay. There are cheaper ways to find out if you'd thrive:\n\n"
                "- **Work weekend shifts** at a busy independent café for 2–3 months\n"
                "- **Run a pop-up or cart** at farmers' markets to test your concept and build a list\n"
                "- **Take over an existing café** instead of building one; equipment and foot traffic "
                "come with it\n\n"
                "Your strongest leverage is your marketing skill. A pop-up that sells out on "
                "weekends is proof for lenders, landlords, and yourself."
            ),
        },
        {
            "member": "operator",
            "round": 1,
            "sources": [],
            "text": (
                "If you pursue it, sequence it so every step is reversible until the last one:\n\n"
                "1. **This month:** write a one-page budget and your personal runway number\n"
                "2. **Months 1–3:** weekend barista shifts plus 10 conversations with café owners\n"
                "3. **Months 3–6:** run a pop-up; track sales, margins, and how you feel at 6am\n"
                "4. **Month 6:** decide using real numbers, then pick between a takeover and a build-out\n\n"
                "**Keep your job until step 4.** Quitting is the last move, not the first."
            ),
        },
        {
            "member": "analyst",
            "round": 2,
            "sources": [],
            "text": (
                "I agree with **the Strategist**: a pop-up gives us data we can't get any other way. "
                "Real weekend sales numbers will tell us more than any industry average I can quote."
            ),
        },
        {
            "member": "skeptic",
            "round": 2,
            "sources": [],
            "text": (
                "**The Operator's** plan answers most of my concerns: nothing irreversible happens "
                "before month six. I'd add one rule: set your walk-away numbers *before* the pop-up "
                "starts, so excitement can't move the goalposts."
            ),
        },
        {
            "member": "strategist",
            "round": 2,
            "sources": [],
            "text": (
                "I disagree slightly with **the Skeptic's** framing. The goal isn't to talk you out "
                "of it but to make it a smart bet. A takeover could cut the startup cost in half, "
                "and that's worth exploring early, not at month six."
            ),
        },
        {
            "member": "operator",
            "round": 2,
            "sources": [],
            "text": (
                "Good catch from **the Strategist**: I'll move \"talk to two café brokers about "
                "takeovers\" into the first three months. The rest of the sequence holds."
            ),
        },
    ],
    "verdict": {
        "headline": "Not yet. Test it for six months while keeping your job.",
        "verdict": (
            "The board thinks the dream is worth pursuing, but quitting now would bet your savings "
            "on assumptions you haven't tested. Six months of barista shifts and a weekend pop-up "
            "will tell you whether you love the work and whether the numbers hold, at a fraction "
            "of the risk."
        ),
        "confidence": 78,
        "votes": [
            {"advisor": "analyst", "position": "for", "reason": "Real pop-up sales beat industry averages."},
            {"advisor": "skeptic", "position": "for", "reason": "Nothing irreversible before month six."},
            {"advisor": "strategist", "position": "mixed", "reason": "Explore takeovers sooner."},
            {"advisor": "operator", "position": "for", "reason": "Every step stays reversible."},
        ],
        "risks": [
            "Signing a lease with a personal guarantee before the concept is proven.",
            "Underestimating the hours and staffing demands of daily operations.",
            "Letting excitement override the walk-away numbers you set in advance.",
        ],
        "first_move": "Write down your personal runway number and the café budget on one page.",
        "steps": [
            {"title": "Know your numbers", "detail": "One-page budget and personal runway, in months.", "when": "This week", "id": 0, "done": False},
            {"title": "Work the floor", "detail": "Weekend shifts at a busy independent café.", "when": "Months 1–3", "id": 0, "done": False},
            {"title": "Talk to owners and brokers", "detail": "Ten café owners, plus two brokers about takeovers.", "when": "Months 1–3", "id": 0, "done": False},
            {"title": "Run a pop-up", "detail": "Track sales, margins, and how you feel at 6am.", "when": "Months 3–6", "id": 0, "done": False},
            {"title": "Decide with data", "detail": "Compare results against your walk-away numbers.", "when": "Month 6", "id": 0, "done": False},
        ],
        "review": "At month six, compare pop-up results with your walk-away numbers before resigning.",
    },
}
SAMPLE_MEETING["steps"] = SAMPLE_MEETING["verdict"].pop("steps")
