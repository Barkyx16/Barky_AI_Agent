"""Engines that produce the board's words: Claude for real, and a scripted demo."""

from __future__ import annotations

import asyncio
import hashlib
from typing import AsyncIterator, Callable, Protocol

import anthropic

from .board import CHAIR_SYSTEM, REBUTTAL_MARKER, Advisor, Verdict, advisor_system

# Opt into server-side refusal fallbacks: if a safety classifier declines a request,
# the API re-runs it on Anthropic's recommended fallback model in the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Event tuples yielded by Engine.take():
#   ("text", str)            - streamed words
#   ("status", str)          - what the advisor is doing (e.g. searching the web)
#   ("sources", list[dict])  - web pages the advisor consulted ({"title", "url"})
#   ("usage", dict)          - tokens and searches billed for one API call (see _usage)
Event = tuple[str, object]


class EngineError(Exception):
    """A user-presentable failure."""


class Engine(Protocol):
    name: str

    def take(self, advisor: Advisor, prompt: str) -> AsyncIterator[Event]: ...

    async def verdict(self, prompt: str, on_usage: Callable[[dict], None] | None = None) -> Verdict: ...


class ClaudeEngine:
    name = "claude"

    def __init__(self, model: str, web_search: bool, client: anthropic.AsyncAnthropic | None = None):
        self.model = model
        self.web_search = web_search
        self.client = client or anthropic.AsyncAnthropic()

    async def take(self, advisor: Advisor, prompt: str) -> AsyncIterator[Event]:
        tools = []
        if advisor.web_search and self.web_search:
            tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 3})
        messages: list[dict] = [{"role": "user", "content": prompt}]
        sources: dict[str, str] = {}

        # A server-side tool loop can pause (stop_reason "pause_turn"); resuming means
        # re-sending the paused assistant turn as-is. Cap resumes so a turn can't spin.
        for _ in range(4):
            try:
                async with self.client.beta.messages.stream(
                    model=self.model,
                    max_tokens=16000,
                    system=advisor_system(advisor),
                    messages=messages,
                    thinking={"type": "adaptive"},
                    output_config={"effort": "low"},
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                    **({"tools": tools} if tools else {}),
                ) as stream:
                    async for event in stream:
                        if event.type == "text":
                            yield ("text", event.text)
                        elif (
                            event.type == "content_block_start"
                            and event.content_block.type == "server_tool_use"
                        ):
                            yield ("status", "Researching on the web…")
                    message = await stream.get_final_message()
            except anthropic.APIError as exc:
                raise EngineError(_friendly(exc)) from exc
            yield ("usage", _usage(message))

            for block in message.content:
                if block.type == "web_search_tool_result" and isinstance(block.content, list):
                    for result in block.content:
                        url = getattr(result, "url", None)
                        if url and url not in sources and len(sources) < 6:
                            sources[url] = getattr(result, "title", None) or url
            if message.stop_reason == "pause_turn":
                messages = [*messages, {"role": "assistant", "content": message.content}]
                continue
            if message.stop_reason == "refusal":
                yield ("text", "\n\n_I'll abstain on this one — it's outside what I can advise on._")
            break

        if sources:
            yield ("sources", [{"url": u, "title": t} for u, t in sources.items()])

    async def verdict(self, prompt: str, on_usage: Callable[[dict], None] | None = None) -> Verdict:
        try:
            response = await self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=CHAIR_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                output_format=Verdict,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIError as exc:
            raise EngineError(_friendly(exc)) from exc
        if on_usage:
            on_usage(_usage(response))
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise EngineError(
                "The Chair couldn't reach a verdict on this one. Try rephrasing the question."
            )
        return response.parsed_output


def _usage(message) -> dict:
    u = getattr(message, "usage", None)
    if u is None:
        return {}
    server = getattr(u, "server_tool_use", None)
    return {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_write_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "web_searches": (getattr(server, "web_search_requests", 0) or 0) if server else 0,
    }


def _friendly(exc: anthropic.APIError) -> str:
    if isinstance(exc, anthropic.AuthenticationError):
        return "The server's Anthropic API key is invalid. Ask the site owner to check it."
    if isinstance(exc, anthropic.RateLimitError):
        return "The board is at capacity right now. Please try again in a minute."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Couldn't reach the AI service. Check the connection and try again."
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return "The AI service had a hiccup. Please try again."
    return "Something went wrong talking to the AI service. Please try again."


# ---------------------------------------------------------------------------
# Demo engine: lets anyone try the full experience with no API key.


def _topic(prompt: str) -> str:
    marker = "The person's question or problem:\n"
    start = prompt.find(marker)
    text = prompt[start + len(marker):] if start >= 0 else prompt
    first = text.strip().split("\n", 1)[0].strip().rstrip("?.!")
    return (first[:90] + "…") if len(first) > 90 else first


DEMO_OPENINGS = {
    "analyst": (
        "Start with the numbers behind **“{t}”**. People in a similar position tend to "
        "underestimate how long a transition takes, so plan for roughly twice your first "
        "estimate. Three facts will decide this: your monthly runway, the realistic upside "
        "in year one, and how reversible the move is.\n\n"
        "- Write down your real figures before deciding\n"
        "- Talk to two people who have made the same move\n\n"
        "_Demo mode: with an API key connected, I research live data on the web._"
    ),
    "skeptic": (
        "The main risk with **“{t}”** isn't failure. It's drifting into it half-committed. "
        "Watch for:\n\n"
        "- **Hidden costs** you haven't priced in yet: time, money, relationships\n"
        "- Making the call while stressed or exhausted\n"
        "- No exit plan if it goes sideways\n\n"
        "None of these are deal-breakers. Set a clear line in advance: *if X hasn't happened "
        "by date Y, I stop or change course.*"
    ),
    "strategist": (
        "This isn't a yes-or-no decision. Before committing fully to **“{t}”**, there is a "
        "third path: **run a small, cheap experiment first.** Give it two to four weeks on a "
        "fixed budget and let the results decide.\n\n"
        "Your most underused lever is people who are a few steps ahead of you. One "
        "conversation can save months."
    ),
    "operator": (
        "Here is how I'd execute **“{t}”**:\n\n"
        "1. **Today:** define what success looks like in 90 days\n"
        "2. **This week:** collect the numbers and two outside opinions\n"
        "3. **Next two weeks:** run the smallest possible test\n"
        "4. **Day 30:** review the results and make the full call\n\n"
        "Put each step on your calendar now. Plans that aren't scheduled don't happen."
    ),
}

DEMO_OPENINGS["guest"] = (
    "Speaking as **{name}**: the board is giving you solid analysis on **“{t}”**, so let me add "
    "the perspective you invited me for. Ask yourself which choice you'd be prouder to explain "
    "a year from now. **Pick the option you can commit to fully**, then give it a fair, "
    "time-boxed chance.\n\n_Demo mode: with an API key connected, I speak fully in the voice you describe._"
)

DEMO_REBUTTALS = {
    "analyst": "I agree with **the Strategist**: a small test replaces guesses with data. The Skeptic's risks are real, but most of them are measurable, so let's measure them.",
    "skeptic": "**The Operator's** timeline eases my main concern. A fixed review date is exactly the exit line I asked for. I'd still resist moving fast before the numbers are in.",
    "strategist": "I partly disagree with **the Skeptic**: waiting for certainty is its own risk. But the Analyst is right that two conversations with people who've done it could change the picture.",
    "guest": "From where I sit, **the Skeptic and the Strategist are both right**: protect the downside, but don't let fear make the decision for you.",
    "operator": "The Strategist's experiment fits step 3 exactly. The Skeptic convinced me to add one thing: **write the stop-rule down before you start**, not after.",
}


class DemoEngine:
    name = "demo"

    def __init__(self, delay: float = 0.025):
        self.delay = delay

    async def take(self, advisor: Advisor, prompt: str) -> AsyncIterator[Event]:
        rebuttal = REBUTTAL_MARKER in prompt
        template = (DEMO_REBUTTALS if rebuttal else DEMO_OPENINGS)[advisor.key]
        text = template.format(t=_topic(prompt), name=advisor.name)
        # Stagger advisors so the discussion feels live.
        offset = int(hashlib.md5(advisor.key.encode()).hexdigest(), 16) % 5
        await asyncio.sleep(self.delay * offset * 4)
        if advisor.web_search and not rebuttal:
            yield ("status", "Researching on the web…")
            await asyncio.sleep(self.delay * 20)
        for i, word in enumerate(text.split(" ")):
            yield ("text", word if i == 0 else " " + word)
            await asyncio.sleep(self.delay)

    async def verdict(self, prompt: str, on_usage: Callable[[dict], None] | None = None) -> Verdict:
        await asyncio.sleep(self.delay * 30)
        t = _topic(prompt)
        return Verdict.model_validate(
            {
                "headline": "Test it small before you commit fully.",
                "verdict": (
                    f"The board leans toward pursuing “{t}”, but not all at once. A short, "
                    "low-cost experiment gives you real evidence, and a written stop-rule "
                    "caps the downside."
                ),
                "confidence": 72,
                "votes": [
                    {"advisor": "analyst", "position": "for", "reason": "Real data beats estimates."},
                    {"advisor": "skeptic", "position": "mixed", "reason": "Only if the stop-rule is written first."},
                    {"advisor": "strategist", "position": "for", "reason": "The experiment is the third path."},
                    {"advisor": "operator", "position": "for", "reason": "It fits a clean 30-day plan."},
                    {"advisor": "guest", "position": "for", "reason": "Commit fully, but time-box it."},
                ],
                "risks": [
                    "Costs in time and money that haven't been priced in yet.",
                    "Drifting in half-committed without a clear finish line.",
                    "Deciding under stress instead of on evidence.",
                ],
                "first_move": "Write down what success looks like in 90 days, and your stop-rule.",
                "steps": [
                    {"title": "Define success", "detail": "Describe a great outcome 90 days from now.", "when": "Today"},
                    {"title": "Get the numbers", "detail": "List costs, runway, and realistic upside.", "when": "This week"},
                    {"title": "Talk to two people", "detail": "Ask people a few steps ahead of you what they would do.", "when": "This week"},
                    {"title": "Run a small test", "detail": "Try the smallest version for two weeks on a fixed budget.", "when": "Next 2 weeks"},
                    {"title": "Make the full call", "detail": "Review results against your stop-rule.", "when": "Day 30"},
                ],
                "review": "In 30 days, compare the test results with your definition of success.",
            }
        )


def make_engine(settings) -> Engine:
    if settings.demo_mode:
        return DemoEngine(delay=settings.demo_delay)
    return ClaudeEngine(model=settings.model, web_search=settings.web_search)
