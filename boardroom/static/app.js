"use strict";

/* Boardroom front end: a small dependency-free single-page app. */

const state = {
  config: null,
  user: null,
  meetings: [],
  view: null,        // "new" | "meeting"
  meetingId: null,
  live: null,        // live meeting being streamed
  mode: "quick",
  draft: { question: "", context: "" },
  guest: { name: "", perspective: "" },
};

const EXAMPLES = [
  "Should I quit my stable job to go full-time on my side business?",
  "We have $40k saved. Pay off the mortgage faster or invest it?",
  "Is it worth going back to school for a master's degree at 34?",
  "My landlord won't return my deposit. What should I do?",
  "Should we move cities for my partner's new job offer?",
  "How should I price my first freelance design project?",
];

const GUEST_PRESETS = [
  { name: "Your future self", perspective: "You, ten years from now, looking back on this decision with hindsight and honesty." },
  { name: "A seasoned founder", perspective: "Someone who has started and sold companies; bias to action, allergic to waste." },
  { name: "A frugal planner", perspective: "A conservative financial planner focused on cash flow, emergency funds, and long-term security." },
  { name: "A wise grandparent", perspective: "Decades of life experience; cares most about relationships, health, and regret." },
];

const $app = document.getElementById("app");
const advisorsByKey = (guest) => Object.fromEntries([...state.config.board, ...(guest ? [guest] : [])].map((a) => [a.key, a]));
const boardAdvisors = () => state.config.board.filter((a) => a.key !== "chair");
const seatsFor = (guest) => (guest ? [...boardAdvisors(), guest] : boardAdvisors());

/* ---------- utilities ---------------------------------------------------- */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function inline(text) {
  let s = esc(text);
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, t, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>`);
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  s = s.replace(/(^|[\s(])_([^_\s][^_]*)_/g, "$1<em>$2</em>");
  return s;
}

/* Minimal, safe markdown: paragraphs, bullet and numbered lists, bold, italics, links. */
function md(text) {
  const out = [];
  let list = null;
  let para = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; } };
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of String(text || "").split("\n")) {
    const line = raw.trim();
    const ul = line.match(/^[-*•]\s+(.*)$/);
    const ol = line.match(/^\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      flushPara();
      const kind = ul ? "ul" : "ol";
      if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline((ul || ol)[1])}</li>`);
    } else if (!line) {
      flushPara(); closeList();
    } else {
      closeList();
      para.push(line.replace(/^#+\s*/, ""));
    }
  }
  flushPara(); closeList();
  return out.join("");
}

/* CSP forbids inline style attributes, so dynamic styles are applied from data attributes. */
function applyStyles(root = document) {
  root.querySelectorAll("[data-c]").forEach((el) => el.style.setProperty("--c", el.dataset.c));
  root.querySelectorAll("[data-w]").forEach((el) => { el.style.width = `${el.dataset.w}%`; });
  root.querySelectorAll("[data-p]").forEach((el) => el.style.setProperty("--p", el.dataset.p));
}

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove("show"), 2600);
}

function timeAgo(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 604800) return `${Math.floor(s / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = friendlyValidation(data.detail);
    } catch (_) { /* keep default */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.headers.get("content-type")?.includes("json") ? res.json() : res;
}

function friendlyValidation(items) {
  const first = items[0] || {};
  const field = (first.loc || []).slice(-1)[0];
  if (field === "password") return "Password must be at least 8 characters.";
  if (field === "name") return "Please enter your name.";
  if (field === "question") return "Please describe your question in a few more words.";
  return first.msg || "Please check your input.";
}

/* ---------- theme -------------------------------------------------------- */

function initTheme() {
  try {
    const saved = localStorage.getItem("theme");
    if (saved) document.documentElement.dataset.theme = saved;
  } catch (_) { /* storage unavailable */ }
}

function toggleTheme() {
  const isDark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = isDark ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch (_) { /* ignore */ }
}

const ICON_THEME = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`;
const ICON_GEAR = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>`;
const ICON_MENU = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>`;
const ICON_PLUS = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`;

/* ---------- landing / auth ---------------------------------------------- */

function renderLanding(tab = "signup") {
  const seats = boardAdvisors().map((a) => `
    <div class="seat"><div class="avatar" data-c="${a.color}">${esc(a.initials)}</div>
      <div><strong>${esc(a.name)}</strong><span>${esc(a.role)}</span></div></div>`).join("");
  $app.innerHTML = `
    <div class="landing">
      <section class="landing-hero">
        <div class="brand"><img src="/static/favicon.svg" alt=""> Boardroom</div>
        <h1>Every hard decision deserves a board meeting.</h1>
        <p class="lede">Bring any decision to a private board of AI advisors. They research the facts, argue it out in front of you, and the Chair hands you a verdict and a plan you can start today.</p>
        <div class="seats">${seats}</div>
        <div class="how"><span><b>1</b>Ask your question</span><span><b>2</b>Watch the board debate</span><span><b>3</b>Get a verdict and a plan</span></div>
      </section>
      <section class="landing-auth">
        <div class="auth-card">
          <h2>${tab === "signup" ? "Take your seat" : "Welcome back"}</h2>
          <p class="sub">${tab === "signup" ? "Create a free account. It takes ten seconds." : "Sign in to see your meetings."}</p>
          <div class="tabs" role="tablist">
            <button role="tab" aria-selected="${tab === "signup"}" data-tab="signup">Create account</button>
            <button role="tab" aria-selected="${tab === "login"}" data-tab="login">Sign in</button>
          </div>
          <form id="auth-form" novalidate>
            ${tab === "signup" ? `<div class="field"><label for="name">Your first name</label><input class="input" id="name" name="name" autocomplete="given-name" required maxlength="60"></div>` : ""}
            <div class="field"><label for="email">Email</label><input class="input" id="email" name="email" type="email" autocomplete="email" required></div>
            <div class="field"><label for="password">Password</label><input class="input" id="password" name="password" type="password" autocomplete="${tab === "signup" ? "new-password" : "current-password"}" required minlength="8" placeholder="${tab === "signup" ? "At least 8 characters" : ""}"></div>
            <p class="error-text" id="auth-error"></p>
            <button class="btn btn-primary btn-block" type="submit">${tab === "signup" ? "Create free account" : "Sign in"}</button>
          </form>
          <p class="fine">${state.config.free_daily_limit} free meetings a day. No card needed.${state.config.demo ? " Running in demo mode." : ""}</p>
        </div>
      </section>
    </div>`;
  applyStyles($app);
  $app.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => renderLanding(b.dataset.tab)));
  const form = document.getElementById("auth-form");
  form.querySelector("input").focus();
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = Object.fromEntries(new FormData(form));
    const btn = form.querySelector("button[type=submit]");
    const errEl = document.getElementById("auth-error");
    errEl.textContent = "";
    btn.disabled = true;
    try {
      state.user = await api(tab === "signup" ? "/api/signup" : "/api/login", { method: "POST", body: fd });
      await enterApp();
    } catch (err) {
      errEl.textContent = err.message;
      btn.disabled = false;
    }
  });
}

/* ---------- app shell ---------------------------------------------------- */

async function enterApp() {
  state.meetings = await api("/api/meetings");
  renderShell();
  route();
}

function renderShell() {
  $app.innerHTML = `
    <div class="shell" id="shell">
      <aside class="sidebar" aria-label="Meetings">
        <div class="brand"><img src="/static/favicon.svg" alt=""> Boardroom</div>
        <a class="btn btn-primary btn-block" href="#/new">${ICON_PLUS} New meeting</a>
        <nav class="history" id="history"></nav>
        <div class="account" id="account"></div>
      </aside>
      <div class="scrim" id="scrim"></div>
      <div>
        <header class="topbar">
          <button class="btn btn-ghost btn-sm" id="menu" aria-label="Open menu">${ICON_MENU}</button>
          <div class="brand"><img src="/static/favicon.svg" alt=""> Boardroom</div>
          <a class="btn btn-ghost btn-sm" href="#/new" aria-label="New meeting">${ICON_PLUS}</a>
        </header>
        <main class="main"><div class="container" id="view"></div></main>
      </div>
    </div>`;
  document.getElementById("menu").addEventListener("click", () => document.getElementById("shell").classList.add("nav-open"));
  document.getElementById("scrim").addEventListener("click", closeNav);
  renderHistory();
  renderAccount();
}

function closeNav() { document.getElementById("shell")?.classList.remove("nav-open"); }

function renderHistory() {
  const el = document.getElementById("history");
  if (!el) return;
  if (!state.meetings.length) {
    el.innerHTML = `<h4>Your meetings</h4><p class="empty-history">No meetings yet. Your first one is a question away.</p>`;
    return;
  }
  el.innerHTML = `<h4>Your meetings</h4>` + state.meetings.map((m) => {
    const pct = m.total_steps ? Math.round((100 * m.done_steps) / m.total_steps) : 0;
    const meta = m.status === "done"
      ? `<span class="mini-bar"><i data-w="${pct}"></i></span><span>${m.done_steps}/${m.total_steps}</span>`
      : `<span>${m.status === "running" ? "In session" : "Unfinished"}</span>`;
    return `<a href="#/m/${m.id}" ${state.meetingId === m.id ? 'aria-current="page"' : ""}>
      <div class="q">${esc(m.headline || m.question)}</div>
      <div class="meta"><span>${timeAgo(m.created_at)}</span>${meta}</div></a>`;
  }).join("");
  applyStyles(el);
}

function renderAccount() {
  const el = document.getElementById("account");
  if (!el || !state.user) return;
  const u = state.user.usage;
  const limited = u.daily_limit !== null;
  const pct = limited ? Math.min(100, Math.round((100 * u.used_today) / u.daily_limit)) : 0;
  el.innerHTML = `
    <div class="account-row"><span class="who">${esc(state.user.name)}</span>
      <span class="badge">${u.plan === "pro" ? "Pro" : state.config.demo ? "Demo" : "Free"}</span></div>
    ${limited ? `<div class="usage">${u.used_today} of ${u.daily_limit} meetings today<div class="usage-bar"><i data-w="${pct}"></i></div></div>` : ""}
    <div class="account-row">
      ${u.plan !== "pro" && !state.config.demo
        ? `<button class="btn btn-sm" id="upgrade">Upgrade to Pro</button>`
        : state.user.can_manage_billing ? `<button class="btn btn-ghost btn-sm" id="billing">Manage billing</button>` : "<span></span>"}
      <span><button class="btn btn-ghost btn-sm" id="settings" aria-label="Account settings">${ICON_GEAR}</button><button class="btn btn-ghost btn-sm" id="theme" aria-label="Toggle theme">${ICON_THEME}</button>
      <button class="btn btn-ghost btn-sm" id="logout">Sign out</button></span>
    </div>`;
  applyStyles(el);
  document.getElementById("theme").addEventListener("click", toggleTheme);
  document.getElementById("settings").addEventListener("click", showSettings);
  document.getElementById("logout").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST" });
    state.user = null; state.meetings = []; state.live = null;
    location.hash = "";
    renderLanding("login");
  });
  document.getElementById("upgrade")?.addEventListener("click", showUpgrade);
  document.getElementById("billing")?.addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try { location.href = (await api("/api/billing/portal", { method: "POST" })).url; } catch (err) { toast(err.message); e.currentTarget.disabled = false; }
  });
}

function showUpgrade() {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="up-title">
      <span class="badge">Boardroom Pro</span>
      <h2 id="up-title">A board that's always in session</h2>
      <ul><li>Unlimited meetings every day</li><li>Deep debates: advisors rebut each other before the Chair rules</li><li>Priority access during busy hours</li></ul>
      ${state.config.billing
        ? `<p class="price"><strong>${esc(state.config.pro_price)}</strong> · cancel anytime</p>
           <p class="error-text" id="up-error"></p>
           <div class="actions"><button class="btn btn-ghost" id="close-up">Not now</button><button class="btn btn-primary" id="go-pro">Upgrade to Pro</button></div>`
        : `<p class="fine">Pro upgrades are handled by the site owner. Contact them to upgrade your account.</p>
           <div class="actions"><button class="btn btn-primary" id="close-up">Got it</button></div>`}
    </div>`;
  document.body.appendChild(back);
  const close = () => back.remove();
  back.addEventListener("click", (e) => { if (e.target === back) close(); });
  back.querySelector("#close-up").addEventListener("click", close);
  const go = back.querySelector("#go-pro");
  go?.addEventListener("click", async () => {
    go.disabled = true;
    try {
      const { url } = await api("/api/billing/checkout", { method: "POST" });
      location.href = url;
    } catch (err) {
      back.querySelector("#up-error").textContent = err.message;
      go.disabled = false;
    }
  });
  (go || back.querySelector("#close-up")).focus();
}

function showSettings() {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="set-title">
      <h2 id="set-title">Account</h2>
      <p class="fine left">${esc(state.user.email)}</p>
      <form id="pw-form" class="settings-block">
        <h3>Change password</h3>
        <div class="field"><label for="pw-cur">Current password</label><input class="input" id="pw-cur" type="password" autocomplete="current-password" required></div>
        <div class="field"><label for="pw-new">New password</label><input class="input" id="pw-new" type="password" autocomplete="new-password" minlength="8" required placeholder="At least 8 characters"></div>
        <p class="error-text" id="pw-error"></p>
        <button class="btn" type="submit">Update password</button>
      </form>
      <details class="settings-block danger">
        <summary>Delete account</summary>
        <form id="del-form">
          <p class="fine left">This permanently deletes your account, meetings, plans and share links. It can't be undone.${state.user.usage.plan === "pro" && state.config.billing ? " Cancel your subscription under <b>Manage billing</b> first." : ""}</p>
          <div class="field"><label for="del-pw">Confirm with your password</label><input class="input" id="del-pw" type="password" autocomplete="current-password" required></div>
          <p class="error-text" id="del-error"></p>
          <button class="btn btn-danger" type="submit">Delete my account</button>
        </form>
      </details>
      <div class="actions"><button class="btn btn-ghost" id="set-close">Close</button></div>
    </div>`;
  document.body.appendChild(back);
  const close = () => back.remove();
  back.addEventListener("click", (e) => { if (e.target === back) close(); });
  back.querySelector("#set-close").addEventListener("click", close);
  back.querySelector("#pw-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = back.querySelector("#pw-error");
    err.textContent = "";
    try {
      await api("/api/account/password", { method: "POST", body: { current_password: back.querySelector("#pw-cur").value, new_password: back.querySelector("#pw-new").value } });
      toast("Password updated. Other devices were signed out.");
      close();
    } catch (ex) { err.textContent = ex.message; }
  });
  back.querySelector("#del-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = back.querySelector("#del-error");
    err.textContent = "";
    try {
      await api("/api/account", { method: "DELETE", body: { password: back.querySelector("#del-pw").value } });
      close();
      state.user = null; state.meetings = []; state.live = null;
      location.hash = "";
      renderLanding("signup");
      toast("Your account has been deleted.");
    } catch (ex) { err.textContent = ex.message; }
  });
  back.querySelector("#pw-cur").focus();
}

async function refreshSidebar() {
  try {
    [state.meetings, state.user] = await Promise.all([api("/api/meetings"), api("/api/me")]);
  } catch (_) { return; }
  renderHistory();
  renderAccount();
}

/* ---------- routing ------------------------------------------------------ */

function route() {
  if (!state.user) return;
  closeNav();
  if (location.hash === "#/billing/success") {
    history.replaceState(null, "", "#/new");
    welcomePro();
  }
  const m = location.hash.match(/^#\/m\/(\d+)/);
  if (m) {
    state.view = "meeting";
    state.meetingId = Number(m[1]);
    renderHistory();
    if (state.live && state.live.id === state.meetingId) renderLive();
    else loadMeeting(state.meetingId);
  } else {
    state.view = "new";
    state.meetingId = null;
    renderHistory();
    renderComposer();
  }
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", () => {
  if (/^#\/s\//.test(location.hash) || document.querySelector(".public")) { location.reload(); return; }
  route();
});

/* Stripe's webhook can land a moment after the redirect, so poll briefly. */
async function welcomePro() {
  toast("Payment received. Activating Pro…");
  for (let i = 0; i < 10; i++) {
    await refreshSidebar();
    if (state.user?.usage.plan === "pro") {
      toast("Welcome to Boardroom Pro");
      if (state.view === "new") renderComposer();
      return;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  toast("Pro will activate as soon as your payment is confirmed.");
}

/* ---------- composer ----------------------------------------------------- */

function demoBanner() {
  return state.config.demo
    ? `<div class="demo-banner"><span class="badge">Demo</span>You're seeing scripted advisors. Add an Anthropic API key on the server for real, researched advice.</div>`
    : "";
}

function renderComposer(prefill) {
  const view = document.getElementById("view");
  const deepOk = state.user.usage.deep_mode;
  if (prefill) state.draft = { ...state.draft, ...prefill };
  delete view.dataset.layout;
  view.innerHTML = `
    ${demoBanner()}
    <div class="composer-head">
      <h1>What's on the table${state.user.name ? `, ${esc(state.user.name)}` : ""}?</h1>
      <p>Describe a decision or problem. Four advisors will weigh in at once, then the Chair makes the call.</p>
    </div>
    <form class="composer" id="composer">
      <label class="sr-only" for="question">Your question</label>
      <textarea class="textarea" id="question" maxlength="2000" placeholder="e.g. Should I take the job offer in Denver or stay where I am?">${esc(state.draft.question)}</textarea>
      <details ${state.draft.context ? "open" : ""}>
        <summary>Add background (optional)</summary>
        <label class="sr-only" for="context">Background</label>
        <textarea class="textarea" id="context" maxlength="6000" placeholder="Anything the board should know: numbers, constraints, what you've tried, what matters most to you.">${esc(state.draft.context)}</textarea>
      </details>
      <details class="guest-seat" ${state.guest.name ? "open" : ""}>
        <summary>Seat a guest advisor (optional)</summary>
        <div class="guest-fields">
          <div class="chips">${GUEST_PRESETS.map((g, i) => `<button class="chip guest-preset" type="button" data-preset="${i}">${esc(g.name)}</button>`).join("")}</div>
          <div class="guest-row">
            <label class="sr-only" for="guest-name">Guest name</label>
            <input class="input" id="guest-name" maxlength="60" placeholder="Who should join? e.g. “My business mentor”" value="${esc(state.guest.name)}">
            <label class="sr-only" for="guest-perspective">Their perspective</label>
            <input class="input" id="guest-perspective" maxlength="400" placeholder="What perspective do they bring?" value="${esc(state.guest.perspective)}">
          </div>
        </div>
      </details>
      <div class="composer-foot">
        <div>
          <div class="segmented" role="group" aria-label="Meeting type">
            <button type="button" data-mode="quick" aria-pressed="${state.mode === "quick"}">Quick session</button>
            <button type="button" data-mode="deep" aria-pressed="${state.mode === "deep"}">Deep debate ${deepOk ? "" : '<span class="pro">PRO</span>'}</button>
          </div>
          <div class="mode-hint" id="mode-hint"></div>
        </div>
        <button class="btn btn-primary" type="submit" id="convene">Convene the board <span class="kbd">⌘↵</span></button>
      </div>
      <p class="error-text" id="composer-error"></p>
    </form>
    <div class="examples"><h4>Or try one of these</h4><div class="chips">
      ${EXAMPLES.map((q) => `<button class="chip" type="button">${esc(q)}</button>`).join("")}
    </div></div>`;

  const q = document.getElementById("question");
  const ctx = document.getElementById("context");
  const hint = document.getElementById("mode-hint");
  const setHint = () => {
    hint.textContent = state.mode === "deep"
      ? "Opening remarks, then a rebuttal round, then the verdict. About 2 minutes."
      : "Opening remarks from all four advisors, then the verdict. About a minute.";
  };
  setHint();
  q.focus();
  q.setSelectionRange(q.value.length, q.value.length);
  q.addEventListener("input", () => { state.draft.question = q.value; });
  ctx.addEventListener("input", () => { state.draft.context = ctx.value; });
  view.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.mode === "deep" && !deepOk) { showUpgrade(); return; }
    state.mode = b.dataset.mode;
    view.querySelectorAll("[data-mode]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    setHint();
  }));
  const gName = document.getElementById("guest-name");
  const gPersp = document.getElementById("guest-perspective");
  gName.addEventListener("input", () => { state.guest.name = gName.value; });
  gPersp.addEventListener("input", () => { state.guest.perspective = gPersp.value; });
  view.querySelectorAll(".guest-preset").forEach((c) => c.addEventListener("click", () => {
    const g = GUEST_PRESETS[Number(c.dataset.preset)];
    gName.value = g.name; gPersp.value = g.perspective;
    state.guest = { ...g };
  }));
  view.querySelectorAll(".examples .chip").forEach((c) => c.addEventListener("click", () => {
    q.value = c.textContent; state.draft.question = q.value; q.focus();
  }));
  const form = document.getElementById("composer");
  form.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const question = q.value.trim();
    if (question.length < 3) {
      document.getElementById("composer-error").textContent = "Tell the board a little more about your question.";
      q.focus();
      return;
    }
    const guestName = gName.value.trim();
    if (guestName && guestName.length < 2) {
      document.getElementById("composer-error").textContent = "Give your guest advisor a name of at least two letters.";
      gName.focus();
      return;
    }
    const body = { question, context: ctx.value.trim(), mode: state.mode };
    if (guestName) body.guest = { name: guestName, perspective: gPersp.value.trim() };
    convene(body);
  });
}

/* ---------- live meeting ------------------------------------------------- */

function newLive(body) {
  const remarks = {};
  for (const a of boardAdvisors()) remarks[a.key] = { 1: freshRemark(), 2: freshRemark() };
  return { id: null, guest: null, question: body.question, context: body.context, mode: body.mode, rounds: [1], remarks, chair: "waiting", verdict: null, steps: [], error: null, running: true };
}

function freshRemark() { return { text: "", status: "Thinking…", done: false, sources: [] }; }

async function convene(body) {
  const btn = document.getElementById("convene");
  if (btn) btn.disabled = true;
  let res;
  try {
    res = await fetch("/api/meetings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      credentials: "same-origin", body: JSON.stringify(body),
    });
  } catch (_) {
    if (btn) btn.disabled = false;
    toast("Couldn't reach the server. Check your connection.");
    return;
  }
  if (!res.ok) {
    if (btn) btn.disabled = false;
    let msg = "Couldn't start the meeting.";
    try { const d = await res.json(); if (typeof d.detail === "string") msg = d.detail; } catch (_) { /* ignore */ }
    if (res.status === 401) { renderLanding("login"); return; }
    const errEl = document.getElementById("composer-error");
    if (errEl) errEl.textContent = msg; else toast(msg);
    if (res.status === 429 || res.status === 403) showUpgrade();
    return;
  }

  state.draft = { question: "", context: "" };
  state.guest = { name: "", perspective: "" };
  const live = newLive(body);
  state.live = live;
  await follow(res, live);
}

/* Read a server-sent event stream into a live meeting. */
async function follow(res, live) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const chunk = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (line) handleEvent(live, JSON.parse(line.slice(6)));
      }
    }
  } catch (_) {
    if (!live.verdict) live.error = "The connection dropped before the meeting finished.";
  }
  live.running = false;
  if (!live.verdict && !live.error) live.error = "Connection lost. The meeting continues on the server — refresh to catch up.";
  if (state.live === live && state.meetingId === live.id) renderLive();
  refreshSidebar();
}

function handleEvent(live, ev) {
  switch (ev.type) {
    case "meeting":
      live.id = ev.id;
      if (ev.guest) { live.guest = ev.guest; live.remarks.guest = { 1: freshRemark(), 2: freshRemark() }; }
      location.hash = `#/m/${ev.id}`;
      refreshSidebar();
      return;
    case "round_start":
      if (!live.rounds.includes(ev.round)) live.rounds.push(ev.round);
      break;
    case "status":
      live.remarks[ev.advisor][ev.round].status = ev.text;
      break;
    case "delta": {
      const r = live.remarks[ev.advisor][ev.round];
      r.text += ev.text;
      r.status = "Speaking";
      break;
    }
    case "sources":
      live.remarks[ev.advisor][ev.round].sources = ev.sources;
      break;
    case "advisor_done": {
      const r = live.remarks[ev.advisor][ev.round];
      r.done = true; r.status = "Done";
      break;
    }
    case "advisor_error": {
      const r = live.remarks[ev.advisor][ev.round];
      r.done = true; r.status = "Sat out";
      break;
    }
    case "chair_start":
      live.chair = "deliberating";
      break;
    case "verdict":
      live.verdict = ev.verdict;
      live.chair = "done";
      break;
    case "done":
      live.steps = ev.steps;
      break;
    case "error":
      live.error = ev.message;
      break;
    default:
      return;
  }
  if (state.meetingId === live.id) scheduleRender();
}

let renderQueued = false;
function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; if (state.live && state.meetingId === state.live.id) renderLive(); });
}

function renderLive() {
  const live = state.live;
  const view = document.getElementById("view");
  if (!view) return;
  // First paint builds the layout; later paints update in place to keep scrolling smooth.
  const layoutKey = [live.id, live.rounds.length, live.chair, !!live.error, live.steps.length, live.running].join("|");
  if (view.dataset.layout !== layoutKey) {
    view.innerHTML = meetingLayout({
      question: live.question, context: live.context, mode: live.mode, created_at: null, running: live.running,
      shareable: !!live.verdict, share_token: live.share_token,
    }, live.rounds, (round) => seatsFor(live.guest).map((a) => remarkCard(a, live.remarks[a.key][round], round)).join(""))
      + chairSection(live)
      + (live.error ? errorBox(live.error) : "");
    view.dataset.layout = layoutKey;
    applyStyles(view);
    bindMeetingActions(view, live);
    return;
  }
  for (const round of live.rounds) {
    for (const a of seatsFor(live.guest)) {
      const card = view.querySelector(`[data-card="${a.key}-${round}"]`);
      if (!card) continue;
      const r = live.remarks[a.key][round];
      card.querySelector(".state").outerHTML = stateBadge(r);
      card.querySelector(".body").outerHTML = remarkBody(r);
      const src = card.querySelector(".sources");
      if (r.sources.length && !src) card.insertAdjacentHTML("beforeend", sourcesHtml(r.sources));
    }
  }
}

/* ---------- meeting rendering (shared by live & saved) ------------------- */

function meetingLayout(m, rounds, cardsFor) {
  const when = m.created_at ? timeAgo(m.created_at) : "Now";
  const mode = m.mode === "deep" ? "Deep debate" : "Quick session";
  return `
    ${m.readonly ? "" : demoBanner()}
    <div class="meeting-head">
      <div>
        <div class="eyebrow"><span>${esc(mode)}</span><span>·</span><span>${esc(when)}</span>${m.running ? '<span class="badge">In session</span>' : ""}</div>
        <h1>${esc(m.question)}</h1>
        ${m.context ? `<div class="context">${esc(m.context)}</div>` : ""}
      </div>
      <div class="head-actions">
        ${m.readonly ? "" : `
        <button class="btn btn-sm" data-act="share" ${m.running || !m.shareable ? "disabled" : ""}>${m.share_token ? "Shared" : "Share"}</button>
        <button class="btn btn-ghost btn-sm" data-act="copy" ${m.running ? "disabled" : ""}>Copy summary</button>
        <button class="btn btn-ghost btn-sm" data-act="print" ${m.running ? "disabled" : ""}>Print</button>
        <button class="btn btn-ghost btn-sm" data-act="delete" ${m.running ? "disabled" : ""}>Delete</button>`}
      </div>
    </div>
    ${rounds.map((r) => `
      <div class="section-title">${r === 1 ? "Opening remarks" : "Rebuttals"}</div>
      <div class="grid">${cardsFor(r)}</div>`).join("")}`;
}

function stateBadge(r) {
  const label = r.done ? (r.text ? "Done" : "Sat out") : r.status;
  return `<span class="state ${r.done ? (r.text ? "done" : "out") : ""}"><span class="dot"></span>${esc(label)}</span>`;
}

function remarkBody(r) {
  if (!r.text && r.done) return `<div class="body muted">Didn't speak this round.</div>`;
  if (!r.text) return `<div class="body skeleton" aria-hidden="true"><i></i><i></i><i></i></div>`;
  return `<div class="body prose ${r.done ? "" : "caret"}">${md(r.text)}</div>`;
}

function sourcesHtml(sources) {
  sources = sources.filter((s) => /^https?:\/\//i.test(s.url));
  if (!sources.length) return "";
  return `<div class="sources"><b>Sources</b>${sources.map((s) => {
    let host = s.url;
    try { host = new URL(s.url).hostname.replace(/^www\./, ""); } catch (_) { /* keep url */ }
    return `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer" title="${esc(s.title)}">${esc(host)}</a>`;
  }).join("")}</div>`;
}

function remarkCard(a, r, round) {
  return `<article class="card advisor-card" data-c="${a.color}" data-card="${a.key}-${round}">
    <div class="advisor-head"><div class="avatar" data-c="${a.color}">${esc(a.initials)}</div>
      <div><div class="name">${esc(a.name)}</div><div class="role">${esc(a.role)}</div></div>
      ${stateBadge(r)}</div>
    ${remarkBody(r)}
    ${r.sources && r.sources.length ? sourcesHtml(r.sources) : ""}
  </article>`;
}

function chairSection(m) {
  const chair = advisorsByKey().chair;
  if (m.verdict) return `<div class="section-title">The verdict</div>` + verdictCard(m.verdict, m.steps, false, m.guest) + followupBox();
  if (m.chair === "deliberating") {
    return `<div class="section-title">The verdict</div>
      <div class="card chair-wait"><div class="avatar" data-c="${chair.color}">${chair.initials}</div><p>The Chair is weighing the arguments…</p><div class="spinner"></div></div>`;
  }
  return "";
}

function verdictCard(v, steps, readonly = false, guest = null) {
  const by = advisorsByKey(guest);
  const chair = by.chair;
  const done = steps.filter((s) => s.done).length;
  const pct = steps.length ? Math.round((100 * done) / steps.length) : 0;
  return `<article class="card verdict">
    <div class="verdict-top">
      <div>
        <div class="who"><div class="avatar sm" data-c="${chair.color}">${chair.initials}</div>The Chair rules</div>
        <h2>${esc(v.headline)}</h2>
        <p class="why">${esc(v.verdict)}</p>
      </div>
      <div class="ring" data-p="${v.confidence}" role="img" aria-label="Confidence ${v.confidence} percent"><div><div><strong>${v.confidence}%</strong><span>confidence</span></div></div></div>
    </div>
    <div class="votes">${v.votes.map((x) => {
      const a = by[x.advisor];
      return a ? `<span class="vote" title="${esc(x.reason)}"><span class="avatar sm" data-c="${a.color}">${a.initials}</span><span class="pos ${x.position}">${x.position}</span><span class="reason">${esc(x.reason)}</span></span>` : "";
    }).join("")}</div>
    <div class="verdict-cols">
      <div class="panel first-move"><h3>Your first move · next 24 hours</h3><p>${esc(v.first_move)}</p></div>
      <div class="panel"><h3>Risks to watch</h3><ul>${v.risks.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
    </div>
    <div class="plan">
      <div class="plan-head"><h3>Action plan</h3>
        ${readonly ? "" : `<div class="progress"><span id="plan-count">${done} of ${steps.length} done</span><span class="bar"><i id="plan-bar" data-w="${pct}"></i></span></div>`}</div>
      <ul class="steps">${steps.map((s) => `
        <li><label class="step ${s.done ? "done" : ""}" data-step="${s.id}">
          <input type="checkbox" ${s.done ? "checked" : ""} ${readonly ? "disabled" : ""} aria-label="Mark “${esc(s.title)}” done">
          <div><div class="t">${esc(s.title)}</div><div class="d">${esc(s.detail)}</div></div>
          ${s.when ? `<span class="w">${esc(s.when)}</span>` : ""}
        </label></li>`).join("")}</ul>
      <div class="review"><b>Review:</b><span>${esc(v.review)}</span></div>
    </div>
  </article>`;
}

function followupBox() {
  return `<form class="followup" id="followup">
    <div class="section-title">Follow up</div>
    <div class="row">
      <label class="sr-only" for="fu">Follow-up question</label>
      <input class="input" id="fu" maxlength="2000" placeholder="Ask the board a follow-up, e.g. “What if I wait six months?”">
      <button class="btn btn-primary" type="submit">Reconvene</button>
    </div></form>`;
}

function errorBox(msg) {
  return `<div class="alert" role="alert"><span>${esc(msg)}</span><button class="btn btn-sm" data-act="retry">Try again</button></div>`;
}

function bindMeetingActions(view, m) {
  view.querySelector('[data-act="delete"]')?.addEventListener("click", async () => {
    if (!m.id || !confirm("Delete this meeting? This can't be undone.")) return;
    try {
      await api(`/api/meetings/${m.id}`, { method: "DELETE" });
      if (state.live?.id === m.id) state.live = null;
      toast("Meeting deleted");
      location.hash = "#/new";
      refreshSidebar();
    } catch (err) { toast(err.message); }
  });
  view.querySelector('[data-act="share"]')?.addEventListener("click", (e) => showShare(m, e.currentTarget));
  view.querySelector('[data-act="print"]')?.addEventListener("click", () => window.print());
  view.querySelector('[data-act="copy"]')?.addEventListener("click", async () => {
    if (!m.verdict) { toast("The verdict isn't in yet."); return; }
    const v = m.verdict;
    const lines = [
      `Question: ${m.question}`, "", `Verdict: ${v.headline}`, v.verdict, "", `Confidence: ${v.confidence}%`,
      "", `First move: ${v.first_move}`, "", "Risks:", ...v.risks.map((r) => `- ${r}`),
      "", "Action plan:", ...m.steps.map((s, i) => `${i + 1}. ${s.title} (${s.when}) — ${s.detail}`),
      "", `Review: ${v.review}`,
    ];
    try { await navigator.clipboard.writeText(lines.join("\n")); toast("Summary copied"); } catch (_) { toast("Couldn't access the clipboard"); }
  });
  view.querySelector('[data-act="retry"]')?.addEventListener("click", () => {
    state.live = null;
    location.hash = "#/new";
    setTimeout(() => renderComposer({ question: m.question, context: "" }), 0);
  });
  view.querySelectorAll("[data-step]").forEach((label) => {
    const box = label.querySelector("input");
    box.addEventListener("change", async () => {
      const id = Number(label.dataset.step);
      label.classList.toggle("done", box.checked);
      const step = m.steps.find((s) => s.id === id);
      if (step) step.done = box.checked;
      updatePlanProgress(view, m.steps);
      try {
        await api(`/api/steps/${id}`, { method: "PATCH", body: { done: box.checked } });
        if (m.steps.length && m.steps.every((s) => s.done)) toast("Plan complete. Well done.");
        refreshSidebar();
      } catch (err) {
        box.checked = !box.checked;
        label.classList.toggle("done", box.checked);
        if (step) step.done = box.checked;
        updatePlanProgress(view, m.steps);
        toast(err.message);
      }
    });
  });
  view.querySelector("#followup")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = view.querySelector("#fu").value.trim();
    if (q.length < 3) return;
    e.target.querySelector("button").disabled = true;
    convene({ question: q, context: "", mode: state.mode === "deep" && state.user.usage.deep_mode ? "deep" : "quick", parent_id: m.id });
  });
}

function updatePlanProgress(view, steps) {
  const done = steps.filter((s) => s.done).length;
  const count = view.querySelector("#plan-count");
  const bar = view.querySelector("#plan-bar");
  if (count) count.textContent = `${done} of ${steps.length} done`;
  if (bar) bar.style.width = `${steps.length ? Math.round((100 * done) / steps.length) : 0}%`;
}

async function loadMeeting(id) {
  const view = document.getElementById("view");
  view.innerHTML = `<div class="boot"><div class="spinner"></div></div>`;
  delete view.dataset.layout;
  let m;
  try {
    m = await api(`/api/meetings/${id}`);
  } catch (err) {
    view.innerHTML = `${errorBox(err.status === 404 ? "That meeting doesn't exist." : err.message)}`;
    view.querySelector('[data-act="retry"]').addEventListener("click", () => { location.hash = "#/new"; });
    return;
  }
  if (state.meetingId !== id) return;
  if (m.status === "running" && await attach(m)) return;
  const rounds = [...new Set(m.takes.map((t) => t.round))].sort();
  if (!rounds.length) rounds.push(1);
  const byKey = {};
  for (const t of m.takes) byKey[`${t.member}-${t.round}`] = t;
  const stalled = m.status !== "done";
  m.shareable = m.status === "done";
  view.innerHTML = meetingLayout(m, rounds, (round) => seatsFor(m.guest).map((a) => {
    const t = byKey[`${a.key}-${round}`];
    const r = t ? { text: t.text, done: true, status: "Done", sources: t.sources } : { text: "", done: true, status: "Sat out", sources: [] };
    return remarkCard(a, r, round);
  }).join(""))
    + (m.verdict ? `<div class="section-title">The verdict</div>${verdictCard(m.verdict, m.steps, false, m.guest)}${followupBox()}` : "")
    + (stalled ? errorBox(m.status === "running" ? "This meeting is still in session. Refresh in a moment to see the result." : "This meeting didn't finish.") : "");
  applyStyles(view);
  bindMeetingActions(view, m);
}

function showShare(m, button) {
  const back = document.createElement("div");
  back.className = "modal-back";
  document.body.appendChild(back);
  const close = () => back.remove();
  back.addEventListener("click", (e) => { if (e.target === back) close(); });
  const linkFor = (token) => `${location.origin}/#/s/${token}`;
  const paint = () => {
    back.innerHTML = m.share_token ? `
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="sh-title">
        <h2 id="sh-title">Share this verdict</h2>
        <p class="fine left">Anyone with the link can read the debate and verdict. Your background notes and progress stay private.</p>
        <div class="row-gap"><input class="input" id="share-link" readonly value="${esc(linkFor(m.share_token))}"><button class="btn btn-primary" id="share-copy">Copy</button></div>
        <div class="actions"><button class="btn btn-ghost" id="share-stop">Stop sharing</button><button class="btn" id="share-done">Done</button></div>
      </div>` : `
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="sh-title">
        <h2 id="sh-title">Share this verdict?</h2>
        <p class="fine left">You'll get a public link to the debate, verdict, and plan. Your background notes and progress stay private. You can stop sharing anytime.</p>
        <div class="actions"><button class="btn btn-ghost" id="share-done">Cancel</button><button class="btn btn-primary" id="share-create">Create link</button></div>
      </div>`;
    back.querySelector("#share-done").addEventListener("click", close);
    back.querySelector("#share-create")?.addEventListener("click", async () => {
      try {
        const { token } = await api(`/api/meetings/${m.id}/share`, { method: "POST" });
        m.share_token = token; button.textContent = "Shared"; paint();
      } catch (err) { toast(err.message); }
    });
    back.querySelector("#share-copy")?.addEventListener("click", async () => {
      const input = back.querySelector("#share-link");
      try { await navigator.clipboard.writeText(input.value); toast("Link copied"); } catch (_) { input.select(); }
    });
    back.querySelector("#share-stop")?.addEventListener("click", async () => {
      try {
        await api(`/api/meetings/${m.id}/share`, { method: "DELETE" });
        m.share_token = null; button.textContent = "Share"; toast("Link turned off"); close();
      } catch (err) { toast(err.message); }
    });
    (back.querySelector("#share-copy") || back.querySelector("#share-create")).focus();
  };
  paint();
}

/* Re-join a meeting that's still in session (after a refresh or from another tab). */
async function attach(m) {
  let res;
  try {
    res = await fetch(`/api/meetings/${m.id}/events`, { credentials: "same-origin" });
  } catch (_) { return false; }
  if (!res.ok || state.meetingId !== m.id) return false;
  const live = newLive({ question: m.question, context: m.context, mode: m.mode });
  live.id = m.id;
  state.live = live;
  renderLive();
  await follow(res, live);
  return true;
}

/* ---------- public shared view ------------------------------------------ */

async function renderShared(token) {
  let m;
  try {
    m = await api(`/api/shared/${encodeURIComponent(token)}`);
  } catch (err) {
    $app.innerHTML = `<div class="public"><header class="public-bar"><a class="brand" href="/"><img src="/static/favicon.svg" alt=""> Boardroom</a></header>
      <main class="container narrow"><div class="alert" role="alert"><span>${esc(err.message)}</span><a class="btn btn-sm" href="/">Go to Boardroom</a></div></main></div>`;
    return;
  }
  document.title = `${m.verdict?.headline || m.question} · Boardroom`;
  const rounds = [...new Set(m.takes.map((t) => t.round))].sort();
  const byKey = {};
  for (const t of m.takes) byKey[`${t.member}-${t.round}`] = t;
  $app.innerHTML = `
    <div class="public">
      <header class="public-bar">
        <a class="brand" href="/"><img src="/static/favicon.svg" alt=""> Boardroom</a>
        <a class="btn btn-primary btn-sm" href="/">Convene your own board</a>
      </header>
      <main class="main"><div class="container">
        ${meetingLayout({ ...m, readonly: true }, rounds.length ? rounds : [1], (round) => seatsFor(m.guest).map((a) => {
          const t = byKey[`${a.key}-${round}`];
          return remarkCard(a, { text: t ? t.text : "", done: true, status: "Done", sources: t ? t.sources : [] }, round);
        }).join(""))}
        ${m.verdict ? `<div class="section-title">The verdict</div>${verdictCard(m.verdict, m.steps, true, m.guest)}` : ""}
        <section class="cta card">
          <h2>Have a decision of your own?</h2>
          <p>Bring it to a private board of AI advisors. They debate it live, and the Chair hands you a verdict and a plan.</p>
          <a class="btn btn-primary" href="/">Start free</a>
        </section>
      </div></main>
    </div>`;
  applyStyles($app);
}

/* ---------- boot ---------------------------------------------------------- */

async function boot() {
  initTheme();
  const shared = location.hash.match(/^#\/s\/([\w-]+)/);
  try {
    state.config = await api("/api/config");
  } catch (_) {
    $app.innerHTML = `<div class="boot"><p>Boardroom is unavailable right now. Please refresh in a moment.</p></div>`;
    return;
  }
  if (shared) { renderShared(shared[1]); return; }
  try {
    state.user = await api("/api/me");
  } catch (_) {
    state.user = null;
  }
  if (state.user) await enterApp();
  else renderLanding(location.hash === "#/login" ? "login" : "signup");
}

boot();
