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
  filter: "",
  focus: "",
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
  root.querySelectorAll("[data-flex]").forEach((el) => { el.style.flexGrow = el.dataset.flex; });
  root.querySelectorAll("[data-top]").forEach((el) => { el.style.top = `${el.dataset.top}%`; });
}

function toast(msg, kind) {
  const el = document.getElementById("toast");
  kind = kind || (/couldn|can't|failed|error|invalid|too many|incorrect|dropped|blocked/i.test(msg) ? "error" : "ok");
  el.className = `toast-${kind}`;
  el.innerHTML = `<span class="toast-icon">${kind === "error" ? ICON.alert : ICON.check}</span><span></span>`;
  el.lastElementChild.textContent = msg;
  void el.offsetWidth;  // restart the entrance transition
  el.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove("show"), kind === "error" ? 4200 : 2600);
}

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function addDaysIso(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const isDue = (reviewAt) => !!reviewAt && reviewAt <= todayIso();

function timeAgo(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 604800) return `${Math.floor(s / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

/* A thin progress line at the top while requests take longer than a blink. */
const loadbar = { n: 0, timer: null };
function loadStart() {
  if (loadbar.n++ > 0) return;
  clearTimeout(loadbar.timer);
  loadbar.timer = setTimeout(() => {
    let el = document.getElementById("loadbar");
    if (!el) { el = document.createElement("div"); el.id = "loadbar"; el.setAttribute("aria-hidden", "true"); document.body.appendChild(el); }
    el.style.transition = "none"; el.style.width = "0"; void el.offsetWidth; el.style.transition = "";
    el.classList.add("on"); el.style.width = "72%";
  }, 160);
}
function loadEnd() {
  if (--loadbar.n > 0) return;
  clearTimeout(loadbar.timer);
  const el = document.getElementById("loadbar");
  if (!el || !el.classList.contains("on")) return;
  el.style.width = "100%";
  setTimeout(() => { el.classList.remove("on"); }, 260);
}

async function api(path, opts = {}) {
  loadStart();
  try { return await apiRaw(path, opts); } finally { loadEnd(); }
}

async function apiRaw(path, opts = {}) {
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

const ACCENTS = [["gold", "Gold", "#b08f52"], ["sapphire", "Sapphire", "#2f5fb8"], ["emerald", "Emerald", "#1b7353"], ["rose", "Rose", "#c2466e"], ["violet", "Violet", "#6c4cc4"]];

function initTheme() {
  try {
    const saved = localStorage.getItem("theme");
    if (saved) document.documentElement.dataset.theme = saved;
    const accent = localStorage.getItem("accent");
    if (accent && accent !== "gold") document.documentElement.dataset.accent = accent;
  } catch (_) { /* storage unavailable */ }
}

function setAccent(key) {
  if (key === "gold") delete document.documentElement.dataset.accent;
  else document.documentElement.dataset.accent = key;
  try { localStorage.setItem("accent", key); } catch (_) { /* fine */ }
  document.querySelectorAll("[data-swatch]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.swatch === key)));
}

const currentAccent = () => document.documentElement.dataset.accent || "gold";

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
const ICON_MIC = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>`;
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition || null;
const svg = (d, size = 16) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const ICON = {
  share: svg('<path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7"/><path d="M12 3v12"/><path d="m7 8 5-5 5 5"/>'),
  copy: svg('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>'),
  print: svg('<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>'),
  trash: svg('<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>'),
  search: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
  arrowDown: svg('<path d="M12 5v14"/><path d="m6 13 6 6 6-6"/>', 15),
  check: svg('<path d="m5 12 5 5 9-10"/>', 15),
  info: svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>', 15),
  alert: svg('<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17h.01"/>', 15),
  moon: svg('<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>'),
  sun: svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  image: svg('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>'),
  up: svg('<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>', 15),
  keyboard: svg('<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>'),
  star: svg('<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>'),
  doc: svg('<path d="M6 3h9l3 3v15H6z"/><path d="M9 11h6M9 15h6"/>'),
  bolt: svg('<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>'),
  gear: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
};
/* Each advisor's glyph; guests (named by the user) keep their initials. */
const GLYPH = {
  analyst: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.6-4.6"/><path d="M8 12.5v-2M10.5 12.5V8M13 12.5v-3"/>',
  skeptic: '<path d="M12 3 4.5 6v5.5c0 4.6 3.1 8.2 7.5 9.5 4.4-1.3 7.5-4.9 7.5-9.5V6z"/><path d="M12 8v4.5M12 15.5h.01"/>',
  strategist: '<circle cx="12" cy="12" r="8.5"/><path d="m15.5 8.5-2.2 4.8-4.8 2.2 2.2-4.8z"/>',
  operator: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="m3.5 6 1.2 1.2L7 5M3.5 12l1.2 1.2L7 11M3.5 18l1.2 1.2L7 17"/>',
  chair: '<path d="m13.5 4.5 6 6M10.5 7.5l6 6M12 6l4.5 4.5M14.5 12.5 6 21l-3-3 8.5-8.5"/><path d="M14 20h7"/>',
};
const avatarInner = (a) => GLYPH[a.key]
  ? `<svg viewBox="0 0 24 24" width="52%" height="52%" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${GLYPH[a.key]}</svg>`
  : esc(a.initials);
const ICON_MENU = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>`;
const ICON_PLUS = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`;

/* ---------- dialogs ------------------------------------------------------ */

/* Shows a dialog: Escape closes it, Tab stays inside, focus returns to the opener. */
function openModal(back) {
  const opener = document.activeElement;
  const close = () => back.remove();
  back.closeModal = close;
  back.addEventListener("click", (e) => { if (e.target === back) close(); });
  document.body.appendChild(back);
  const watcher = new MutationObserver(() => {
    if (!back.isConnected) {
      watcher.disconnect();
      if (opener && opener.isConnected) opener.focus();
    }
  });
  watcher.observe(document.body, { childList: true });
  return close;
}

document.addEventListener("keydown", (e) => {
  const backs = document.querySelectorAll(".modal-back");
  const top = backs[backs.length - 1];
  if (!top) return;
  if (e.key === "Escape") { e.preventDefault(); top.closeModal(); return; }
  if (e.key !== "Tab") return;
  const items = [...top.querySelectorAll("button, a[href], input, summary, textarea, [tabindex]:not([tabindex='-1'])")]
    .filter((el) => !el.disabled && el.offsetParent !== null);
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  else if (!top.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
});

/* ---------- landing / auth ---------------------------------------------- */

function pendingRef() {
  try {
    const fromUrl = new URLSearchParams(location.search).get("ref");
    if (fromUrl) sessionStorage.setItem("ref", fromUrl);
    return sessionStorage.getItem("ref");
  } catch (_) {
    return new URLSearchParams(location.search).get("ref");
  }
}

/* The landing page's little play: each advisor speaks in turn, then the Chair rules. */
const SCENE = [
  ["analyst", "Three facts decide this: your runway, the realistic upside, and how reversible it is."],
  ["skeptic", "The real risk isn't failing. It's drifting into it half-committed."],
  ["strategist", "This isn't yes-or-no. Run a small, cheap test first."],
  ["operator", "Step one, today: write down what success looks like in 90 days."],
  ["chair", "Verdict: test it for six months while keeping your job. 78% confident."],
];
let sceneTimer = null;

function runScene() {
  clearTimeout(sceneTimer);
  const line = document.getElementById("scene-line");
  if (!line) return;
  const names = Object.fromEntries(state.config.board.map((a) => [a.key, a.name]));
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let turn = 0;
  const speak = () => {
    if (!line.isConnected) return;  // left the landing page
    const [key, text] = SCENE[turn % SCENE.length];
    document.querySelectorAll("[data-seat]").forEach((el) => el.classList.toggle("talking", el.dataset.seat === key));
    line.innerHTML = `<b>${esc(names[key] || "")}</b><span class="typed"></span>`;
    const out = line.querySelector(".typed");
    if (still) { out.textContent = text; out.classList.remove("typed"); turn++; sceneTimer = setTimeout(speak, 4200); return; }
    let i = 0;
    const type = () => {
      if (!line.isConnected) return;
      i += 2;
      out.textContent = text.slice(0, i);
      if (i < text.length) sceneTimer = setTimeout(type, 28);
      else { out.classList.remove("typed"); turn++; sceneTimer = setTimeout(speak, key === "chair" ? 3400 : 1700); }
    };
    type();
  };
  speak();
}

/* Play the entrance animation for elements the first time they appear, not on re-renders. */
const seenAnim = new Map();  // key -> when it first appeared
let animScope = "page";
function animateNew(root) {
  const now = performance.now();
  root.querySelectorAll("[data-anim]").forEach((el) => {
    const first = seenAnim.get(el.dataset.anim);
    if (first === undefined) seenAnim.set(el.dataset.anim, now);
    const since = first === undefined ? 0 : now - first;
    // An element re-created mid-animation picks up where the old one was, instead of
    // replaying from the start or snapping to the end.
    if (since > 1800) return;
    el.style.setProperty("--since", `${Math.round(since)}ms`);
    el.classList.add("enter");
  });
}

/* Below the fold on the landing page: how it works, pricing, and a last nudge. */
function marketingSections() {
  const L = state.config.limits;
  const by = Object.fromEntries(state.config.board.map((a) => [a.key, a]));
  const mini = (k) => `<span class="avatar sm" data-c="${by[k].color}">${avatarInner(by[k])}</span>`;
  const showPricing = state.config.billing || state.config.demo;
  const tick = `<span class="lp-tick">${ICON.check}</span>`;
  return `
    <section class="lp-section lp-how" aria-labelledby="how-title">
      <p class="lp-kicker">How it works</p>
      <h2 id="how-title">A whole board, in about a minute.</h2>
      <div class="lp-cards">
        <article class="lp-card">
          <div class="lp-visual vis-ask"><div class="vis-chips"><i>Career</i><i class="on">Money</i><i>Business</i></div><div class="vis-line"></div><div class="vis-line short"></div><div class="vis-btn">Convene the board</div></div>
          <h3><span class="lp-num">1</span>Bring the decision</h3>
          <p>Type it or say it. Add background, pick a focus, or seat a guest like your future self.</p>
        </article>
        <article class="lp-card">
          <div class="lp-visual vis-debate">${["analyst", "skeptic", "strategist", "operator"].map((k) => `<div class="vis-row">${mini(k)}<div class="vis-line"></div></div>`).join("")}</div>
          <h3><span class="lp-num">2</span>Watch the debate</h3>
          <p>Four advisors weigh in at once, with live research, real risks, smarter options and a plan.</p>
        </article>
        <article class="lp-card">
          <div class="lp-visual vis-verdict"><div class="vis-ring"><b>78%</b></div><ul><li>${tick}<span></span></li><li>${tick}<span></span></li><li class="open"><i></i><span></span></li></ul></div>
          <h3><span class="lp-num">3</span>Get the verdict</h3>
          <p>A clear call, the options scored, your first move, and a plan you can tick off. With reminders.</p>
        </article>
      </div>
    </section>
    ${showPricing ? `
    <section class="lp-section lp-pricing" aria-labelledby="pricing-title">
      <p class="lp-kicker">Pricing</p>
      <h2 id="pricing-title">Start free. Upgrade when it earns its seat.</h2>
      <div class="price-plans">
        <article class="price-plan">
          <h3>Free</h3>
          <p class="price"><b>$0</b> forever</p>
          <ul>
            <li>${tick}${Number(L.free_daily_meetings)} board meetings a day</li>
            <li>${tick}${Number(L.free_deep_per_week)} deep debate a week</li>
            <li>${tick}${Number(L.free_daily_asks)} questions to advisors a day</li>
            <li>${tick}Plans, reminders and share links</li>
          </ul>
          <button class="btn btn-block lp-start" type="button">Start free</button>
        </article>
        <article class="price-plan pro">
          <span class="badge">Most popular</span>
          <h3>Pro</h3>
          <p class="price"><b>${esc(state.config.pro_price.split("/")[0])}</b>${state.config.pro_price.includes("/") ? ` / ${esc(state.config.pro_price.split("/").slice(1).join("/"))}` : ""}</p>
          <ul>
            <li>${tick}Up to ${Number(L.pro_daily_meetings)} meetings a day</li>
            <li>${tick}Unlimited deep debates</li>
            <li>${tick}${Number(L.pro_daily_asks)} questions to advisors a day</li>
            <li>${tick}Everything in Free</li>
          </ul>
          <button class="btn btn-primary btn-block lp-start" type="button">Start free, upgrade anytime</button>
        </article>
      </div>
    </section>` : ""}
    <section class="lp-section lp-faq" aria-labelledby="faq-title">
      <p class="lp-kicker">Questions</p>
      <h2 id="faq-title">Good questions, straight answers.</h2>
      <div class="faq">
        ${[
          ["Is this real advice?", "Boardroom gives you AI-generated perspectives to think with, not professional advice. For big medical, legal or financial decisions, the board will tell you when to bring in a qualified professional, and you should."],
          ["Who are the advisors?", "AI models, each given one job: the Analyst checks facts (and can search the web), the Skeptic hunts for risks, the Strategist finds better options, and the Operator turns it into a plan. The Chair weighs them and makes the call."],
          ["Is what I share private?", "Your meetings are private unless you create a share link, and you can turn a link off anytime. We don't sell your data. Your questions are processed by our AI provider to generate answers, and you can download or delete everything from Settings."],
          ["Does it work in my language?", "Yes. Write your question in any language and the board answers in it."],
          ...(showPricing ? [["What does it cost?", `The free plan includes ${Number(L.free_daily_meetings)} meetings a day and a free deep debate each week. Pro is ${esc(state.config.pro_price)} and you can cancel anytime.`]] : []),
        ].map(([q, a]) => `<details class="faq-item"><summary>${q}<span class="chev" aria-hidden="true"></span></summary><p>${a}</p></details>`).join("")}
      </div>
    </section>
    <section class="lp-section lp-final">
      <h2>What's the decision you keep putting off?</h2>
      <p>Bring it to the board. Your first meeting takes about a minute.</p>
      <button class="btn btn-primary lp-start" type="button">Convene your board</button>
    </section>
    <footer class="lp-footer">
      <div class="brand"><img src="/static/favicon.svg" alt=""> Boardroom</div>
      <nav><a href="/#/sample">Sample meeting</a><a href="/terms">Terms</a><a href="/privacy">Privacy</a></nav>
      <p>AI-generated perspectives, not professional advice. © ${new Date().getFullYear()} Boardroom</p>
    </footer>`;
}

function renderLanding(tab = "signup") {
  const ref = pendingRef();
  const seat = (a) => `<div class="seat-pos pos-${a.key}" data-seat="${a.key}">
      <div class="avatar" data-c="${a.color}">${avatarInner(a)}</div><span>${esc(a.name.replace(/^The /, ""))}</span></div>`;
  const scene = `<div class="scene" role="img" aria-label="The board around a table: the Analyst, the Skeptic, the Strategist and the Operator debate while the Chair listens.">
      <div class="table"><p class="line" id="scene-line" aria-hidden="true"></p></div>
      ${state.config.board.map(seat).join("")}
    </div>`;
  $app.innerHTML = `
    <main class="landing-page">
    <div class="landing">
      <section class="landing-hero">
        <div class="brand"><img src="/static/favicon.svg" alt=""> Boardroom</div>
        <h1>Every hard decision deserves a <span class="hl">board meeting.</span></h1>
        <p class="lede">Bring any decision to a private board of AI advisors. They research the facts, argue it out in front of you, and the Chair hands you a verdict and a plan you can start today.</p>
        ${scene}
        <div class="how"><span><b>1</b>Ask your question</span><span><b>2</b>Watch the board debate</span><span><b>3</b>Get a verdict and a plan</span></div>
        <p class="sample-link"><button class="btn btn-primary mobile-cta" type="button" id="jump-signup">Create a free account</button><a class="btn" href="/#/sample">See a sample meeting <span class="arr" aria-hidden="true">→</span></a></p>
        <p class="legal-links"><a href="/terms">Terms</a> · <a href="/privacy">Privacy</a></p>
      </section>
      <section class="landing-auth">
        <div class="auth-card">
          <h2>${tab === "signup" ? "Take your seat" : "Welcome back"}</h2>
          <p class="sub">${tab === "signup" ? "Create a free account. It takes ten seconds." : "Sign in to see your meetings."}</p>
          ${tab === "signup" && ref && !state.config.demo ? `<div class="notice invite">You were invited. You'll get <b>${Number(state.config.referral_bonus)} bonus meetings</b> when you sign up.</div>` : ""}
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
          ${tab === "login" && state.config.password_reset ? `<p class="fine"><button class="link" id="forgot" type="button">Forgot your password?</button></p>` : ""}
          <p class="fine">${state.config.free_daily_limit} free meetings a day. No card needed.${state.config.demo ? " Running in demo mode." : ""}</p>
          ${tab === "signup" ? `<p class="fine">By creating an account you agree to the <a href="/terms" target="_blank">Terms</a> and <a href="/privacy" target="_blank">Privacy Policy</a>. Boardroom gives AI-generated perspectives, not professional advice.</p>` : ""}
        </div>
      </section>
    </div>
    ${marketingSections()}
    </main>`;
  applyStyles($app);
  runScene();
  $app.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => renderLanding(b.dataset.tab)));
  document.getElementById("forgot")?.addEventListener("click", renderForgot);
  const toSignup = () => {
    if (tab !== "signup") { renderLanding("signup"); window.scrollTo(0, 0); }
    document.querySelector(".landing-auth").scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => document.querySelector("#auth-form input")?.focus({ preventScroll: true }), 450);
  };
  document.getElementById("jump-signup")?.addEventListener("click", toSignup);
  $app.querySelectorAll(".lp-start").forEach((b) => b.addEventListener("click", toSignup));
  const form = document.getElementById("auth-form");
  // On phones, focusing would jump past the hero and open the keyboard straight away.
  if (matchMedia("(min-width: 981px)").matches) form.querySelector("input").focus();
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = Object.fromEntries(new FormData(form));
    if (tab === "signup" && ref) fd.ref = ref;
    const btn = form.querySelector("button[type=submit]");
    const errEl = document.getElementById("auth-error");
    errEl.textContent = "";
    btn.disabled = true;
    try {
      state.user = await api(tab === "signup" ? "/api/signup" : "/api/login", { method: "POST", body: fd });
      await enterApp();
      if (tab === "signup") showTour();
    } catch (err) {
      errEl.textContent = err.message;
      btn.disabled = false;
    }
  });
}

function authFrame(title, sub, inner) {
  $app.innerHTML = `
    <div class="landing single">
      <section class="landing-auth">
        <div class="auth-card">
          <a class="brand" href="/"><img src="/static/favicon.svg" alt=""> Boardroom</a>
          <h2 class="spaced">${title}</h2>
          <p class="sub">${sub}</p>
          ${inner}
        </div>
      </section>
    </div>`;
}

function renderForgot() {
  authFrame("Reset your password", "Enter your account email and we'll send you a link to choose a new password.", `
    <form id="forgot-form" novalidate>
      <div class="field"><label for="email">Email</label><input class="input" id="email" type="email" autocomplete="email" required></div>
      <p class="error-text" id="auth-error"></p>
      <button class="btn btn-primary btn-block" type="submit">Send reset link</button>
    </form>
    <p class="fine"><a href="/#/login">Back to sign in</a></p>`);
  const form = document.getElementById("forgot-form");
  form.querySelector("input").focus();
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button");
    btn.disabled = true;
    try {
      await api("/api/password/forgot", { method: "POST", body: { email: form.querySelector("#email").value } });
      form.outerHTML = `<div class="notice">If an account exists for that email, a reset link is on its way. It expires in an hour.</div>`;
    } catch (err) {
      document.getElementById("auth-error").textContent = err.message;
      btn.disabled = false;
    }
  });
}

function renderReset(token) {
  authFrame("Choose a new password", "Pick something at least 8 characters long.", `
    <form id="reset-form" novalidate>
      <div class="field"><label for="password">New password</label><input class="input" id="password" type="password" autocomplete="new-password" minlength="8" required></div>
      <p class="error-text" id="auth-error"></p>
      <button class="btn btn-primary btn-block" type="submit">Save and sign in</button>
    </form>`);
  const form = document.getElementById("reset-form");
  form.querySelector("input").focus();
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button");
    btn.disabled = true;
    try {
      state.user = await api("/api/password/reset", { method: "POST", body: { token, password: form.querySelector("#password").value } });
      history.replaceState(null, "", "#/new");
      await enterApp();
      toast("Password updated. You're signed in.");
    } catch (err) {
      document.getElementById("auth-error").textContent = err.message;
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
        ${state.user.is_admin ? `<a class="admin-link" href="#/admin">Owner dashboard</a>` : ""}
        <label class="sr-only" for="search">Search meetings</label>
        <div class="search-wrap">${ICON.search}<input class="input search" id="search" type="search" placeholder="Search meetings" autocomplete="off"><button class="kbd-hint" id="open-palette" type="button" aria-label="Open command palette" title="Command palette">${navigator.platform.includes("Mac") ? "⌘" : "Ctrl "}K</button></div>
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
  document.getElementById("open-palette").addEventListener("click", openPalette);
  document.getElementById("search").addEventListener("input", (e) => { state.filter = e.target.value; renderHistory(); });
  renderHistory();
  renderAccount();
}

function closeNav() { document.getElementById("shell")?.classList.remove("nav-open"); }

function renderHistory() {
  const el = document.getElementById("history");
  if (!el) return;
  if (!state.meetings.length) {
    el.innerHTML = `<h2>Your meetings</h2><p class="empty-history">No meetings yet. Your first one is a question away.</p>`;
    return;
  }
  const q = (state.filter || "").trim().toLowerCase();
  const shown = q ? state.meetings.filter((m) => `${m.question} ${m.headline || ""}`.toLowerCase().includes(q)) : state.meetings;
  if (!shown.length) {
    el.innerHTML = `<h2>Your meetings</h2><p class="empty-history">No meetings match “${esc(state.filter.trim())}”.</p>`;
    return;
  }
  const item = (m) => {
    const pct = m.total_steps ? Math.round((100 * m.done_steps) / m.total_steps) : 0;
    const meta = m.status === "done"
      ? `<span class="mini-bar"><i data-w="${pct}"></i></span><span>${m.done_steps}/${m.total_steps}</span>${m.outcome ? `<span class="out out-${esc(m.outcome)}">${esc((OUTCOMES.find(([k]) => k === m.outcome) || ["", ""])[1])}</span>` : isDue(m.review_at) ? '<span class="due">Review due</span>' : ""}`
      : `<span>${m.status === "running" ? "In session" : "Unfinished"}</span>`;
    return `<div class="h-item"><a href="#/m/${m.id}" ${state.meetingId === m.id ? 'aria-current="page"' : ""} ${m.headline ? `title="${esc(m.headline)}"` : ""}>
      <div class="q">${m.pinned ? `<span class="pin-mark" aria-label="Pinned">${ICON.star}</span>` : ""}${esc(m.question)}</div>
      <div class="meta"><span>${timeAgo(m.created_at)}</span>${meta}</div></a>
      <button type="button" class="h-pin ${m.pinned ? "is-on" : ""}" data-pin="${m.id}" aria-pressed="${!!m.pinned}" aria-label="${m.pinned ? "Unpin" : "Pin"}: ${esc(m.question)}">${ICON.star}</button></div>`;
  };
  if (q) {
    el.innerHTML = `<h2>${shown.length} found</h2>` + shown.map(item).join("");
  } else {
    // Group by recency, like a well-kept inbox.
    const day = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const today = day(new Date());
    const bucket = (iso) => {
      const diff = Math.round((today - day(new Date(iso))) / 86400000);
      return diff <= 0 ? "Today" : diff === 1 ? "Yesterday" : diff < 7 ? "Previous 7 days" : diff < 30 ? "Previous 30 days" : "Earlier";
    };
    let html = "", current = "";
    const sorted = [...shown].sort((x, y) => (x.created_at < y.created_at ? 1 : -1));
    const pinned = sorted.filter((m) => m.pinned);
    if (pinned.length) html += `<h2>Pinned</h2>${pinned.map(item).join("")}`;
    for (const m of sorted.filter((x) => !x.pinned)) {
      const b = bucket(m.created_at);
      if (b !== current) { html += `<h2>${b}</h2>`; current = b; }
      html += item(m);
    }
    el.innerHTML = html;
  }
  applyStyles(el);
  el.querySelectorAll("[data-pin]").forEach((b) => b.addEventListener("click", async (e) => {
    e.preventDefault();
    const id = Number(b.dataset.pin), on = b.getAttribute("aria-pressed") !== "true";
    try {
      await api(`/api/meetings/${id}/pin`, { method: "PATCH", body: { pinned: on } });
      const m = state.meetings.find((x) => x.id === id);
      if (m) m.pinned = on;
      renderHistory();
      const tool = document.querySelector('[data-act="pin"]');
      if (tool && state.meetingId === id) { tool.classList.toggle("is-on", on); tool.setAttribute("aria-pressed", String(on)); }
    } catch (err) { toast(err.message); }
  }));
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
    ${limited ? `<div class="usage">${u.used_today} of ${u.daily_limit} meetings today${u.bonus_meetings ? ` · +${u.bonus_meetings} bonus` : ""}<div class="usage-bar"><i data-w="${pct}"></i></div></div>` : ""}
    <div class="account-actions">
      ${u.plan !== "pro" && !state.config.demo ? `<button class="btn btn-sm" id="upgrade">Upgrade to Pro</button>` : ""}
      <button class="btn btn-sm" id="invite">${u.plan !== "pro" && !state.config.demo ? "Invite friends" : `Invite friends${state.config.demo ? "" : ` · +${Number(state.config.referral_bonus)}`}`}</button>
    </div>
    ${state.user.can_manage_billing ? `<button class="btn btn-ghost btn-sm btn-block" id="billing">Manage billing</button>` : ""}
    <div class="account-row">
      <span><button class="btn btn-ghost btn-sm" id="settings" aria-label="Account settings" title="Account settings">${ICON_GEAR}</button><button class="btn btn-ghost btn-sm theme-toggle" id="theme" aria-label="Toggle theme" title="Toggle theme"><span class="i-sun">${ICON.sun}</span><span class="i-moon">${ICON.moon}</span></button></span>
      <button class="btn btn-ghost btn-sm" id="logout">Sign out</button>
    </div>`;
  applyStyles(el);
  document.getElementById("theme").addEventListener("click", toggleTheme);
  document.getElementById("settings").addEventListener("click", showSettings);
  document.getElementById("invite").addEventListener("click", showInvite);
  document.getElementById("logout").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST" });
    state.user = null; state.meetings = []; state.live = null; state.filter = "";
    location.hash = "";
    renderLanding("login");
  });
  document.getElementById("upgrade")?.addEventListener("click", showUpgrade);
  document.getElementById("billing")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try { location.href = (await api("/api/billing/portal", { method: "POST" })).url; } catch (err) { toast(err.message); btn.disabled = false; }
  });
}

function showUpgrade() {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="up-title">
      <span class="badge">Boardroom Pro</span>
      <h2 id="up-title">A board that's always in session</h2>
      <ul><li>Up to ${Number(state.config.limits.pro_daily_meetings)} meetings a day (instead of ${Number(state.config.limits.free_daily_meetings)})</li><li>Unlimited deep debates: advisors rebut each other before the Chair rules</li><li>${Number(state.config.limits.pro_daily_asks)} questions to advisors a day</li></ul>
      ${state.config.billing
        ? `<p class="price"><strong>${esc(state.config.pro_price)}</strong> · cancel anytime</p>
           <p class="error-text" id="up-error"></p>
           <div class="actions"><button class="btn btn-ghost" id="close-up">Not now</button><button class="btn btn-primary" id="go-pro">Upgrade to Pro</button></div>`
        : `<p class="fine">Pro upgrades are handled by the site owner. Contact them to upgrade your account.</p>
           <div class="actions"><button class="btn btn-primary" id="close-up">Got it</button></div>`}
    </div>`;
  const close = openModal(back);
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

async function showInvite() {
  let info;
  try { info = await api("/api/referral"); } catch (err) { toast(err.message); return; }
  const link = `${location.origin}/?ref=${encodeURIComponent(info.code)}`;
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="inv-title">
      <h2 id="inv-title">Invite friends</h2>
      <p class="fine left">Know someone facing a big decision? When they sign up with your link, you both get <b>${Number(info.bonus)} bonus meetings</b>${info.earned >= info.cap ? "" : ` (up to ${Number(info.cap)} for you in total)`}.</p>
      <div class="row-gap"><label class="sr-only" for="invite-link">Your invite link</label><input class="input" id="invite-link" readonly value="${esc(link)}"><button class="btn btn-primary" id="invite-copy">Copy</button></div>
      <p class="fine left">${Number(info.invited)} ${info.invited === 1 ? "friend has" : "friends have"} joined · ${Number(info.earned)} bonus meetings earned</p>
      <div class="actions"><button class="btn" id="invite-done">Done</button></div>
    </div>`;
  const close = openModal(back);
  back.querySelector("#invite-done").addEventListener("click", close);
  back.querySelector("#invite-copy").addEventListener("click", async () => {
    const input = back.querySelector("#invite-link");
    try { await navigator.clipboard.writeText(input.value); toast("Invite link copied"); } catch (_) { input.select(); }
  });
  back.querySelector("#invite-copy").focus();
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
      ${state.config.reminders ? `<div class="settings-block">
        <h3>Emails</h3>
        <label class="toggle"><input type="checkbox" id="remind" ${state.user.remind_emails ? "checked" : ""}> Email me when it's time to review a decision</label>
        <label class="toggle"><input type="checkbox" id="digest" ${state.user.digest_emails ? "checked" : ""}> Weekly digest of my open plan steps</label>
      </div>` : ""}
      <div class="settings-block">
        <h3 id="accent-label">Accent color</h3>
        <div class="swatches" role="radiogroup" aria-labelledby="accent-label">
          ${ACCENTS.map(([k, label, c]) => `<button type="button" class="swatch" role="radio" data-swatch="${k}" data-c="${c}" aria-checked="${currentAccent() === k}" aria-label="${label}" title="${label}"></button>`).join("")}
        </div>
      </div>
      <div class="settings-block">
        <h3>Your data</h3>
        <p class="fine left">Download every meeting, verdict and plan as a JSON file.</p>
        <a class="btn" href="/api/account/export" download>Download my data</a>
      </div>
      <details class="settings-block danger">
        <summary>Delete account</summary>
        <form id="del-form">
          <p class="fine left">This permanently deletes your account, meetings, plans and share links. It can't be undone.${state.user.usage.plan === "pro" && state.config.billing ? " Cancel your subscription under <b>Manage billing</b> first." : ""}</p>
          <div class="field"><label for="del-pw">Confirm with your password</label><input class="input" id="del-pw" type="password" autocomplete="current-password" required></div>
          <p class="error-text" id="del-error"></p>
          <button class="btn btn-danger" type="submit">Delete my account</button>
        </form>
      </details>
      <div class="actions"><span class="legal-links"><a href="/terms" target="_blank">Terms</a> · <a href="/privacy" target="_blank">Privacy</a></span><button class="btn btn-ghost" id="set-close">Close</button></div>
    </div>`;
  const close = openModal(back);
  back.querySelector("#set-close").addEventListener("click", close);
  for (const [id, field, label] of [["remind", "remind_emails", "Review reminders"], ["digest", "digest_emails", "Weekly digest"]]) {
    back.querySelector(`#${id}`)?.addEventListener("change", async (e) => {
      const on = e.target.checked;
      try {
        await api("/api/account/preferences", { method: "PATCH", body: { [field]: on } });
        state.user[field] = on;
        toast(`${label} ${on ? "on" : "off"}`);
      } catch (err) { e.target.checked = !on; toast(err.message); }
    });
  }
  back.querySelectorAll("[data-swatch]").forEach((b) => {
    b.style.setProperty("--sw", b.dataset.c);
    b.addEventListener("click", () => setAccent(b.dataset.swatch));
  });
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
      state.user = null; state.meetings = []; state.live = null; state.filter = "";
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
  const go = () => routeNow();
  // Smooth cross-fade between screens where the browser supports View Transitions.
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches && document.getElementById("view")) {
    const t = document.startViewTransition(go);
    // A newer navigation can cancel this one; that's expected, not an error.
    for (const done of [t.ready, t.finished, t.updateCallbackDone]) done?.catch(() => {});
  } else {
    go();
  }
}

function routeNow() {
  closeNav();
  if (location.hash === "#/billing/success") {
    history.replaceState(null, "", "#/new");
    welcomePro();
  }
  const m = location.hash.match(/^#\/m\/(\d+)/);
  if (location.hash === "#/admin" && state.user.is_admin) {
    state.view = "admin";
    state.meetingId = null;
    renderHistory();
    renderAdmin();
  } else if (m) {
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
  if (/^#\/s\//.test(location.hash) || location.hash === "#/sample" || document.querySelector(".public")) { location.reload(); return; }
  if (!state.user) {
    const reset = location.hash.match(/^#\/reset\/([\w-]+)/);
    if (reset) renderReset(reset[1]);
    else renderLanding(location.hash === "#/login" ? "login" : "signup");
    return;
  }
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
  const freeDeepLeft = state.user.usage.free_deep_left || 0;
  const deepOk = state.user.usage.deep_mode || freeDeepLeft > 0;
  if (state.mode === "deep" && !deepOk) state.mode = "quick";
  if (prefill) state.draft = { ...state.draft, ...prefill };
  delete view.dataset.layout;
  view.innerHTML = `
    ${demoBanner()}
    <div class="composer-head">
      <h1>What's on the table${state.user.name ? `, ${esc(state.user.name)}` : ""}?</h1>
      <p>Describe a decision or problem. Four advisors will weigh in at once, then the Chair makes the call.</p>
    </div>
    <form class="composer" id="composer">
      <div class="focus-row" role="group" aria-label="Board focus">
        <span class="focus-label">Board</span>
        ${[{ key: "", label: "General" }, ...(state.config.focus_areas || [])].map((f) => `<button type="button" class="focus-chip" data-focus="${esc(f.key)}" aria-pressed="${(state.focus || "") === f.key}">${esc(f.label)}</button>`).join("")}
      </div>
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
            <button type="button" data-mode="deep" aria-pressed="${state.mode === "deep"}">Deep debate ${state.user.usage.deep_mode ? "" : freeDeepLeft > 0 ? `<span class="pro free">${freeDeepLeft} FREE</span>` : '<span class="pro">PRO</span>'}</button>
          </div>
          <div class="mode-hint" id="mode-hint"></div>
        </div>
        <div class="submit-row">
          ${SpeechRec ? `<button class="btn btn-ghost mic" type="button" id="mic" aria-pressed="false" aria-label="Speak your question" title="Speak your question">${ICON_MIC}</button>` : ""}
          <button class="btn btn-primary" type="submit" id="convene">Convene the board <span class="kbd">⌘↵</span></button>
        </div>
      </div>
      <p class="error-text" id="composer-error"></p>
    </form>
    <div class="examples"><h2>Or try one of these</h2><div class="chips">
      ${EXAMPLES.map((q) => `<button class="chip" type="button">${esc(q)}</button>`).join("")}
    </div></div>`;

  const q = document.getElementById("question");
  const ctx = document.getElementById("context");
  const hint = document.getElementById("mode-hint");
  const setHint = () => {
    hint.textContent = state.mode === "deep"
      ? `Opening remarks, then a rebuttal round, then the verdict. About 2 minutes.${!state.user.usage.deep_mode ? " Uses your free deep debate for this week." : ""}`
      : "Opening remarks from all four advisors, then the verdict. About a minute.";
  };
  setHint();
  q.focus();
  q.setSelectionRange(q.value.length, q.value.length);
  const grow = () => { q.style.height = "auto"; q.style.height = `${Math.min(q.scrollHeight + 2, 420)}px`; };
  q.addEventListener("input", () => { state.draft.question = q.value; grow(); });
  if (q.value) grow();
  typePlaceholder(q);
  view.querySelectorAll("[data-focus]").forEach((b) => b.addEventListener("click", () => {
    state.focus = b.dataset.focus;
    view.querySelectorAll("[data-focus]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));
  const mic = document.getElementById("mic");
  if (mic) {
    let rec = null;
    const stop = () => { if (rec) { rec.onresult = null; rec.stop(); } };
    document.getElementById("composer").addEventListener("submit", stop);
    mic.addEventListener("click", () => {
      if (rec) { stop(); return; }
      rec = new SpeechRec();
      rec.interimResults = true;
      rec.continuous = true;
      rec.lang = navigator.language || "en-US";
      const base = q.value ? `${q.value.trimEnd()} ` : "";
      rec.onresult = (e) => {
        let text = "";
        for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
        q.value = base + text.trim();
        state.draft.question = q.value;
      };
      rec.onerror = (e) => {
        if (e.error === "not-allowed" || e.error === "service-not-allowed") toast("Microphone access was blocked. Allow it in your browser to speak your question.");
        else if (e.error !== "aborted" && e.error !== "no-speech") toast("Voice input stopped. Please try again.");
      };
      rec.onend = () => { rec = null; mic.setAttribute("aria-pressed", "false"); mic.classList.remove("listening"); q.focus(); };
      try {
        rec.start();
        mic.setAttribute("aria-pressed", "true");
        mic.classList.add("listening");
        toast("Listening… tap the mic again when you're done.");
      } catch (_) { rec = null; }
    });
    window.addEventListener("hashchange", stop, { once: true });
  }
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
    const body = { question, context: ctx.value.trim(), mode: state.mode, focus: state.focus || "" };
    if (guestName) body.guest = { name: guestName, perspective: gPersp.value.trim() };
    convene(body);
  });
}

/* ---------- live meeting ------------------------------------------------- */

function newLive(body) {
  const remarks = {};
  for (const a of boardAdvisors()) remarks[a.key] = { 1: freshRemark(), 2: freshRemark() };
  return { id: null, guest: null, focus: body.focus || "", question: body.question, context: body.context, mode: body.mode, rounds: [1], remarks, chair: "waiting", verdict: null, steps: [], error: null, running: true };
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
      if (ev.focus !== undefined) live.focus = ev.focus;
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
    case "chair_draft":
      live.draft = { headline: ev.headline, verdict: ev.verdict };
      break;
    case "verdict":
      live.verdict = ev.verdict;
      live.chair = "done";
      tabAlert("✓ Verdict ready");
      if (state.meetingId === live.id) requestAnimationFrame(() => requestAnimationFrame(verdictPill));
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
  animScope = `m-${live.id}`;
  if (view.dataset.layout !== layoutKey) {
    view.innerHTML = meetingLayout({
      question: live.question, context: live.context, mode: live.mode, focus: live.focus, created_at: null, running: live.running,
      stage: live.chair !== "waiting" ? "chair" : live.rounds.length > 1 ? "rebuttal" : "opening",
      shareable: !!live.verdict, share_token: live.share_token, id: live.id,
    }, live.rounds, (round) => seatsFor(live.guest).map((a) => {
      const r = live.remarks[a.key][round];
      const askable = round === 1 && live.verdict && !live.running && r.text;
      return remarkCard(a, r, round, askable ? (live.asks || []).filter((x) => x.advisor === a.key) : null);
    }).join(""))
      + chairSection(live)
      + (live.error ? errorBox(live.error) : "");
    view.dataset.layout = layoutKey;
    applyStyles(view);
    animateNew(view);
    countFresh(view);
    clampLong(view);
    bindMeetingActions(view, live);
    return;
  }
  if (live.chair === "deliberating" && live.draft) {
    const h = view.querySelector("#draft-headline");
    const v = view.querySelector("#draft-verdict");
    const st = view.querySelector("#chair-status");
    if (h) h.textContent = live.draft.headline;
    if (v) v.textContent = live.draft.verdict;
    if (st && live.draft.headline) st.textContent = "The Chair is ruling…";
  }
  for (const round of live.rounds) {
    for (const a of seatsFor(live.guest)) {
      const card = view.querySelector(`[data-card="${a.key}-${round}"]`);
      if (!card) continue;
      const r = live.remarks[a.key][round];
      card.querySelector(".state").outerHTML = stateBadge(r);
      card.classList.toggle("speaking", !r.done && !!r.text);
      if (r.done) clampLong(card.parentElement);
      card.querySelector(".body").outerHTML = remarkBody(r);
      const src = card.querySelector(".sources");
      if (r.sources.length && !src) card.insertAdjacentHTML("beforeend", sourcesHtml(r.sources));
    }
  }
}

/* ---------- meeting rendering (shared by live & saved) ------------------- */

/* Live progress: Opening remarks → (Rebuttals) → Verdict. */
function stepper(m) {
  const steps = [["opening", "Opening remarks"], ...(m.mode === "deep" ? [["rebuttal", "Rebuttals"]] : []), ["chair", "Verdict"]];
  const at = steps.findIndex(([k]) => k === m.stage);
  return `<ol class="stepper" aria-label="Meeting progress">${steps.map(([k, label], i) => `
    <li class="${i < at ? "done" : i === at ? "now" : ""}" ${i === at ? 'aria-current="step"' : ""}>
      <span class="bullet">${i < at ? ICON.check : i + 1}</span><span>${label}</span></li>`).join("")}</ol>`;
}

function meetingLayout(m, rounds, cardsFor) {
  const when = m.created_at ? timeAgo(m.created_at) : m.readonly ? "Example" : "Now";
  const focusLabel = (state.config.focus_areas || []).find((f) => f.key === m.focus)?.label;
  const mode = `${m.mode === "deep" ? "Deep debate" : "Quick session"}${focusLabel ? ` · ${focusLabel} board` : ""}`;
  return `
    <div class="mini-head" aria-hidden="true">
      <span class="mini-q">${esc(m.question)}</span>
      <button class="mini-btn" type="button" tabindex="-1" data-mini="verdict">The verdict ${ICON.arrowDown}</button>
      <button class="mini-btn" type="button" tabindex="-1" data-mini="top">Top ${ICON.up}</button>
    </div>
    ${m.readonly ? "" : demoBanner()}
    <div class="meeting-head">
      <div>
        <div class="eyebrow"><span>${esc(mode)}</span><span>·</span><span>${esc(when)}</span>${m.running ? '<span class="badge">In session</span>' : ""}</div>
        <h1>${esc(m.question)}</h1>
        ${m.context ? `<div class="context">${esc(m.context)}</div>` : ""}
      </div>
      <div class="head-actions">
        ${m.readonly ? "" : `
        <div class="toolbar" role="toolbar" aria-label="Meeting actions">
          <button class="tool share ${m.share_token ? "is-on" : ""}" data-act="share" data-tip="${m.share_token ? "Shared · manage link" : "Share"}" aria-label="${m.share_token ? "Shared, manage link" : "Share"}" ${m.running || !m.shareable ? "disabled" : ""}>${ICON.share}<span>${m.share_token ? "Shared" : "Share"}</span></button>
          <button class="tool" data-act="copy" data-tip="Copy summary" aria-label="Copy summary" ${m.running ? "disabled" : ""}>${ICON.copy}</button>
          ${m.id && !m.running ? `<button class="tool pin ${m.pinned ? "is-on" : ""}" data-act="pin" data-tip="${m.pinned ? "Unpin" : "Pin to the top"}" aria-pressed="${!!m.pinned}" aria-label="Pin meeting">${ICON.star}</button>` : ""}
          ${m.id && m.shareable ? `<a class="tool" href="/api/meetings/${Number(m.id)}/card.png" download="boardroom-verdict.png" data-tip="Download verdict image" aria-label="Download verdict image">${ICON.image}</a>` : ""}
          <button class="tool" data-act="print" data-tip="Print or save as PDF" aria-label="Print or save as PDF" ${m.running ? "disabled" : ""}>${ICON.print}</button>
          <button class="tool danger" data-act="delete" data-tip="Delete meeting" aria-label="Delete meeting" ${m.running ? "disabled" : ""}>${ICON.trash}</button>
        </div>`}
      </div>
    </div>
    ${m.running ? stepper(m) : ""}
    ${rounds.map((r) => `
      <div class="section-title">${r === 1 ? "Opening remarks" : "Rebuttals"}</div>
      <div class="grid">${cardsFor(r)}</div>`).join("")}`;
}

function stateBadge(r) {
  const label = r.done ? (r.text ? "Done" : "Sat out") : r.status;
  return `<span class="state ${r.done ? (r.text ? "done" : "out") : ""}"><span class="dot"></span>${esc(label)}</span>`;
}

/* While text is still streaming, hide a bold/italic marker whose closing half hasn't arrived. */
function tidyPartial(text) {
  if ((text.match(/\*\*/g) || []).length % 2) {
    const i = text.lastIndexOf("**");
    text = text.slice(0, i) + text.slice(i + 2);
  }
  return text.replace(/(^|\s)[*_]$/, "$1");
}

function remarkBody(r) {
  if (!r.text && r.done) return `<div class="body muted">Didn't speak this round.</div>`;
  if (!r.text) return `<div class="body skeleton" aria-hidden="true"><i></i><i></i><i></i></div>`;
  return `<div class="body prose ${r.done ? "" : "caret"}">${md(r.done ? r.text : tidyPartial(r.text))}</div>`;
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

function remarkCard(a, r, round, ask = null) {
  return `<article class="card advisor-card ${!r.done && r.text ? "speaking" : ""}" data-c="${a.color}" data-card="${a.key}-${round}" data-anim="${esc(animScope)}-${a.key}-${round}">
    <div class="advisor-head"><div class="avatar" data-c="${a.color}">${avatarInner(a)}</div>
      <div><div class="name">${esc(a.name)}</div><div class="role">${esc(a.role)}</div></div>
      ${stateBadge(r)}</div>
    ${remarkBody(r)}
    ${r.sources && r.sources.length ? sourcesHtml(r.sources) : ""}
    ${ask ? askSection(a, ask) : ""}
  </article>`;
}

function askBubble(q, answerHtml, streaming = false) {
  return `<div class="qa"><div class="q">${esc(q)}</div><div class="a prose ${streaming ? "caret" : ""}">${answerHtml}</div></div>`;
}

function askSection(a, asks) {
  const short = a.name.replace(/^The /, "the ");
  return `<div class="asks" data-asks="${a.key}">
    ${asks.map((x) => askBubble(x.question, md(x.answer))).join("")}
  </div>
  <form class="ask-form" data-ask-form="${a.key}" hidden>
    <label class="sr-only" for="ask-${a.key}">Question for ${esc(a.name)}</label>
    <input class="input" id="ask-${a.key}" maxlength="1000" placeholder="Ask ${esc(short)} anything about this">
    <button class="btn btn-primary btn-sm" type="submit">Ask</button>
  </form>
  <button class="link ask-open" type="button" data-ask-open="${a.key}">Ask ${esc(short)} a question</button>`;
}

/* Stream one advisor's answer to a direct question. */
async function askAdvisor(m, key, question, card) {
  const thread = card.querySelector(".asks");
  thread.insertAdjacentHTML("beforeend", askBubble(question, "", true));
  const bubble = thread.lastElementChild.querySelector(".a");
  let text = "";
  let ok = false;
  try {
    const res = await fetch(`/api/meetings/${m.id}/ask`, {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
      body: JSON.stringify({ advisor: key, question }),
    });
    if (!res.ok) {
      let msg = "Couldn't ask that question.";
      try { const d = await res.json(); if (typeof d.detail === "string") msg = d.detail; } catch (_) { /* ignore */ }
      thread.lastElementChild.remove();
      toast(msg);
      if (res.status === 429 && /Upgrade/.test(msg)) showUpgrade();
      return false;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const line = buffer.slice(0, idx).split("\n").find((l) => l.startsWith("data: "));
        buffer = buffer.slice(idx + 2);
        if (!line) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === "delta") { text += ev.text; bubble.innerHTML = md(tidyPartial(text)); }
        else if (ev.type === "error") { bubble.innerHTML = `<span class="muted">${esc(ev.message)}</span>`; }
        else if (ev.type === "done") {
          ok = true;
          (m.asks = m.asks || []).push({ advisor: key, question, answer: ev.answer });
        }
      }
    }
  } catch (_) {
    bubble.innerHTML = `<span class="muted">The connection dropped. Please try again.</span>`;
  }
  bubble.classList.remove("caret");
  if (!ok && !text) bubble.closest(".qa").classList.add("failed");
  return ok;  // keep the typed question in the box when it didn't go through
}

function chairSection(m) {
  const chair = advisorsByKey().chair;
  if (m.verdict) return `<div class="section-title">The verdict</div>` + verdictCard(m.verdict, m.steps, false, m.guest, addDaysIso(m.verdict.review_in_days || 30), { value: m.outcome, note: m.outcome_note }) + followupBox();
  if (m.chair === "deliberating") {
    return `<div class="section-title">The verdict</div>
      <div class="card chair-wait">
        <div class="chair-wait-head"><div class="avatar" data-c="${chair.color}">${avatarInner(chair)}</div><p id="chair-status">${m.draft && m.draft.headline ? "The Chair is ruling…" : "The Chair is weighing the arguments…"}</p><div class="spinner"></div></div>
        <div class="chair-draft">
          <h2 id="draft-headline">${esc(m.draft?.headline || "")}</h2>
          <p class="why caret-inline" id="draft-verdict">${esc(m.draft?.verdict || "")}</p>
        </div>
      </div>`;
  }
  return "";
}

/* A friendly dead end: an empty table and one clear way forward. */
function emptyState(title, text, cta, href) {
  return `<section class="empty-state" role="status">
    <svg class="empty-art" viewBox="0 0 220 120" aria-hidden="true">
      <ellipse cx="110" cy="66" rx="70" ry="30" class="e-table"/>
      ${[[110, 18], [26, 66], [194, 66], [60, 108], [160, 108]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="9" class="e-seat"/>`).join("")}
    </svg>
    <h1>${esc(title)}</h1>
    <p>${esc(text)}</p>
    <a class="btn btn-primary" href="${esc(href)}">${esc(cta)} <span class="arr" aria-hidden="true">→</span></a>
  </section>`;
}

/* How the board split, as one segmented bar. */
function tallyBar(votes) {
  if (!Array.isArray(votes) || votes.length < 2) return "";
  const order = [["for", "for"], ["mixed", "mixed"], ["against", "against"]];
  const counts = order.map(([k]) => votes.filter((v) => v.position === k).length);
  const parts = order.map(([k, label], i) => ({ k, label, n: counts[i] })).filter((p) => p.n);
  return `<div class="tally" role="img" aria-label="${parts.map((p) => `${p.n} ${p.label}`).join(", ")}">
    <div class="tally-bar">${parts.map((p) => `<i class="t-${p.k}" data-flex="${p.n}"></i>`).join("")}</div>
    <div class="tally-legend" aria-hidden="true">${parts.map((p) => `<span><b class="t-${p.k}"></b>${p.n} ${p.label}</span>`).join("")}</div>
  </div>`;
}

function optionsChart(options) {
  if (!Array.isArray(options) || options.length < 2) return "";
  const rows = options.slice().sort((a, b) => b.score - a.score);
  return `<section class="options" aria-label="Options compared">
    <h3>Options compared <span>fit score, 0–100</span></h3>
    <ol>${rows.map((o, i) => {
      const score = Math.max(0, Math.min(100, Number(o.score) || 0));
      return `<li class="${i === 0 ? "top" : ""}">
        <div class="opt-head"><span class="opt-name">${esc(o.name)}</span>${i === 0 ? '<span class="badge">Recommended</span>' : ""}<span class="opt-score">${score}</span></div>
        <div class="opt-track"><i data-w="${score}"></i></div>
        <div class="opt-sum">${esc(o.summary)}</div>
      </li>`;
    }).join("")}</ol>
  </section>`;
}

const OUTCOMES = [["great", "Went well"], ["mixed", "Mixed"], ["bad", "Didn't work out"]];

function outcomeBox(outcome, note) {
  return `<div class="outcome" data-outcome>
    <div class="outcome-row">
      <span class="outcome-q">${outcome ? "How it turned out" : "How did it turn out?"}</span>
      <div class="segmented" role="group" aria-label="Outcome">
        ${OUTCOMES.map(([k, label]) => `<button type="button" data-outcome-pick="${k}" aria-pressed="${outcome === k}">${label}</button>`).join("")}
      </div>
    </div>
    <form class="outcome-note" ${outcome ? "" : "hidden"}>
      <label class="sr-only" for="outcome-note">What happened?</label>
      <input class="input" id="outcome-note" maxlength="1000" placeholder="What happened? (optional)" value="${esc(note || "")}">
      <button class="btn btn-sm" type="submit">Save note</button>
    </form>
  </div>`;
}

function verdictCard(v, steps, readonly = false, guest = null, reviewAt = null, outcome = undefined) {
  const anim = `${animScope}-verdict`;
  const by = advisorsByKey(guest);
  const chair = by.chair;
  const done = steps.filter((s) => s.done).length;
  const pct = steps.length ? Math.round((100 * done) / steps.length) : 0;
  return `<article class="card verdict" data-anim="${esc(anim)}">
    <div class="verdict-top">
      <div>
        <div class="who"><div class="avatar sm" data-c="${chair.color}">${avatarInner(chair)}</div>The Chair rules</div>
        <h2>${esc(v.headline)}</h2>
        <p class="why">${esc(v.verdict)}</p>
      </div>
      <div class="ring" data-p="${Number(v.confidence)}" role="img" aria-label="Confidence ${Number(v.confidence)} percent"><div><div><strong data-count="${Number(v.confidence)}">${Number(v.confidence)}%</strong><span>confidence</span></div></div></div>
    </div>
    <div class="votes">${v.votes.map((x) => {
      const a = by[x.advisor];
      return a ? `<span class="vote" title="${esc(x.reason)}"><span class="avatar sm" data-c="${esc(a.color)}" title="${esc(a.name)}">${avatarInner(a)}</span><span class="sr-only">${esc(a.name)}:</span><span class="pos ${esc(x.position)}">${esc(x.position)}</span><span class="reason">${esc(x.reason)}</span></span>` : "";
    }).join("")}</div>
    ${tallyBar(v.votes)}
    ${optionsChart(v.options)}
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
      <div class="review ${!readonly && isDue(reviewAt) ? "is-due" : ""}">
        <b>${reviewAt ? `Review ${isDue(reviewAt) ? "due" : "on"} ${esc(fmtDay(reviewAt))}:` : "Review:"}</b><span>${esc(v.review)}</span>
        ${!readonly && isDue(reviewAt) ? `<button class="btn btn-primary btn-sm" data-act="review">Hold a review</button>` : ""}
      </div>
      ${!readonly && outcome !== undefined ? outcomeBox(outcome?.value, outcome?.note) : ""}
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

/* A slim bar that keeps the question in view once you scroll past the title. */
function bindMiniHead(root) {
  const bar = root.querySelector(".mini-head");
  const title = root.querySelector(".meeting-head h1");
  if (!bar || !title) return;
  const io = new IntersectionObserver(([e]) => bar.classList.toggle("show", !e.isIntersecting && e.boundingClientRect.top < 0));
  io.observe(title);
  bar.querySelector('[data-mini="top"]').addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  const toVerdict = bar.querySelector('[data-mini="verdict"]');
  toVerdict.hidden = !root.querySelector(".verdict, .chair-wait");
  toVerdict.addEventListener("click", () => root.querySelector(".verdict, .chair-wait")?.scrollIntoView({ behavior: "smooth", block: "start" }));
}

function bindMeetingActions(view, m) {
  bindMiniHead(view);
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
  view.querySelector('[data-act="pin"]')?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const on = btn.getAttribute("aria-pressed") !== "true";
    try {
      await api(`/api/meetings/${m.id}/pin`, { method: "PATCH", body: { pinned: on } });
      m.pinned = on;
      btn.classList.toggle("is-on", on);
      btn.setAttribute("aria-pressed", String(on));
      btn.dataset.tip = on ? "Unpin" : "Pin to the top";
      toast(on ? "Pinned to the top of your meetings" : "Unpinned");
      refreshSidebar();
    } catch (err) { toast(err.message); }
  });
  view.querySelector('[data-act="share"]')?.addEventListener("click", (e) => showShare(m, e.currentTarget));
  view.querySelectorAll("[data-ask-open]").forEach((btn) => btn.addEventListener("click", () => {
    const card = btn.closest(".advisor-card");
    const form = card.querySelector("[data-ask-form]");
    form.hidden = false;
    btn.hidden = true;
    form.querySelector("input").focus();
  }));
  view.querySelectorAll("[data-ask-form]").forEach((form) => form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = form.querySelector("input");
    const q = input.value.trim();
    if (q.length < 3) return;
    const btn = form.querySelector("button");
    btn.disabled = true; input.disabled = true;
    const ok = await askAdvisor(m, form.dataset.askForm, q, form.closest(".advisor-card"));
    btn.disabled = false; input.disabled = false;
    if (ok) input.value = "";
    input.focus();
  }));
  const box = view.querySelector("[data-outcome]");
  if (box) {
    const save = async (value, note) => {
      await api(`/api/meetings/${m.id}/outcome`, { method: "PATCH", body: { outcome: value, note } });
      m.outcome = value; m.outcome_note = note;
    };
    box.querySelectorAll("[data-outcome-pick]").forEach((b) => b.addEventListener("click", async () => {
      const value = m.outcome === b.dataset.outcomePick ? null : b.dataset.outcomePick;  // click again to clear
      try {
        await save(value, value ? (m.outcome_note || "") : "");
        box.querySelectorAll("[data-outcome-pick]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.outcomePick === value)));
        box.querySelector(".outcome-q").textContent = value ? "How it turned out" : "How did it turn out?";
        box.querySelector(".outcome-note").hidden = !value;
        if (value) { toast("Outcome saved. Thanks for closing the loop."); box.querySelector("#outcome-note").focus(); }
        refreshSidebar();
      } catch (err) { toast(err.message); }
    }));
    box.querySelector(".outcome-note").addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await save(m.outcome, box.querySelector("#outcome-note").value.trim()); toast("Note saved"); } catch (err) { toast(err.message); }
    });
  }
  view.querySelector('[data-act="review"]')?.addEventListener("click", () => {
    const input = view.querySelector("#fu");
    if (!input) return;
    input.value = "Review time. Here's what happened since our last meeting: ";
    input.scrollIntoView({ behavior: "smooth", block: "center" });
    input.focus();
  });
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
      if (box.checked) navigator.vibrate?.(12);
      updatePlanProgress(view, m.steps);
      try {
        await api(`/api/steps/${id}`, { method: "PATCH", body: { done: box.checked } });
        if (m.steps.length && m.steps.every((s) => s.done)) { toast("Plan complete. Well done."); confetti(); navigator.vibrate?.([20, 40, 30]); }
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
  view.innerHTML = meetingSkeleton();
  delete view.dataset.layout;
  let m;
  try {
    m = await api(`/api/meetings/${id}`);
  } catch (err) {
    view.innerHTML = err.status === 404
      ? emptyState("This meeting isn't here", "It may have been deleted, or the link is wrong.", "Start a new meeting", "#/new")
      : errorBox(err.message);
    view.querySelector('[data-act="retry"]')?.addEventListener("click", () => { location.hash = "#/new"; });
    return;
  }
  if (state.meetingId !== id) return;
  if (m.status === "running" && await attach(m)) return;
  animScope = `m-${id}`;
  const rounds = [...new Set(m.takes.map((t) => t.round))].sort();
  if (!rounds.length) rounds.push(1);
  const byKey = {};
  for (const t of m.takes) byKey[`${t.member}-${t.round}`] = t;
  const stalled = m.status !== "done";
  m.shareable = m.status === "done";
  view.innerHTML = meetingLayout(m, rounds, (round) => seatsFor(m.guest).map((a) => {
    const t = byKey[`${a.key}-${round}`];
    const r = t ? { text: t.text, done: true, status: "Done", sources: t.sources } : { text: "", done: true, status: "Sat out", sources: [] };
    return remarkCard(a, r, round, round === 1 && m.status === "done" && t ? (m.asks || []).filter((x) => x.advisor === a.key) : null);
  }).join(""))
    + (m.verdict ? `<div class="section-title">The verdict</div>${verdictCard(m.verdict, m.steps, false, m.guest, m.review_at, { value: m.outcome, note: m.outcome_note })}${followupBox()}` : "")
    + (stalled ? errorBox(m.status === "running" ? "This meeting is still in session. Refresh in a moment to see the result." : "This meeting didn't finish.") : "");
  applyStyles(view);
  animateNew(view);
  countFresh(view);
  clampLong(view);
  bindMeetingActions(view, m);
}

function markShared(button, on) {
  button.classList.toggle("is-on", on);
  button.querySelector("span").textContent = on ? "Shared" : "Share";
  button.dataset.tip = on ? "Shared · manage link" : "Share";
  button.setAttribute("aria-label", on ? "Shared, manage link" : "Share");
}

function showShare(m, button) {
  const back = document.createElement("div");
  back.className = "modal-back";
  const close = openModal(back);
  const linkFor = (token) => `${location.origin}/s/${token}`;
  const paint = () => {
    back.innerHTML = m.share_token ? `
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="sh-title">
        <h2 id="sh-title">Share this verdict</h2>
        <p class="fine left">Anyone with the link can read the debate and verdict. Your background notes and progress stay private.</p>
        <div class="row-gap"><label class="sr-only" for="share-link">Share link</label><input class="input" id="share-link" readonly value="${esc(linkFor(m.share_token))}"><button class="btn btn-primary" id="share-copy">Copy</button></div>
        ${navigator.share ? `<button class="btn btn-block native-share" id="share-native">${ICON.share} Share…</button>` : ""}
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
        m.share_token = token; markShared(button, true); paint();
      } catch (err) { toast(err.message); }
    });
    back.querySelector("#share-native")?.addEventListener("click", async () => {
      const url = linkFor(m.share_token);
      const data = { title: "The board's verdict", text: m.verdict?.headline ? `“${m.question}” — ${m.verdict.headline}` : m.question, url };
      try {
        // Attach the verdict image where the platform can share files.
        const res = await fetch(`/api/meetings/${m.id}/card.png`, { credentials: "same-origin" });
        const file = new File([await res.blob()], "boardroom-verdict.png", { type: "image/png" });
        if (navigator.canShare?.({ files: [file] })) data.files = [file];
      } catch (_) { /* share the link alone */ }
      try { await navigator.share(data); } catch (err) { if (err.name !== "AbortError") toast("Sharing didn't work here. Copy the link instead."); }
    });
    back.querySelector("#share-copy")?.addEventListener("click", async () => {
      const input = back.querySelector("#share-link");
      try { await navigator.clipboard.writeText(input.value); toast("Link copied"); } catch (_) { input.select(); }
    });
    back.querySelector("#share-stop")?.addEventListener("click", async () => {
      try {
        await api(`/api/meetings/${m.id}/share`, { method: "DELETE" });
        m.share_token = null; markShared(button, false); toast("Link turned off"); close();
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
  const live = newLive({ question: m.question, context: m.context, mode: m.mode, focus: m.focus });
  live.id = m.id;
  state.live = live;
  renderLive();
  await follow(res, live);
  return true;
}

/* ---------- owner dashboard ---------------------------------------------- */

const fmtInt = (n) => Number(n || 0).toLocaleString();
const fmtUsd = (n, digits = 2) => {
  const v = Number(n || 0);
  return `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
};
const fmtPct = (n) => `${(100 * (n || 0)).toFixed(1)}%`;
const fmtDay = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });

function niceMax(v) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

/* Single-series column chart: thin bars, rounded data-end, hairline grid, hover tooltip. */
function columnChart(id, rows, key, fmt) {
  const W = 460, H = 170, L = 40, R = 6, T = 10, B = 24;
  const max = niceMax(Math.max(...rows.map((r) => r[key])));
  const band = (W - L - R) / rows.length;
  const bw = Math.min(24, band - 2);
  const y = (v) => T + (H - T - B) * (1 - v / max);
  const ticks = [0, max / 2, max];
  const grid = ticks.map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>
    <text class="tick" x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${esc(fmt(t))}</text>`).join("");
  const bars = rows.map((r, i) => {
    const x = L + i * band + (band - bw) / 2;
    const top = y(r[key]), base = y(0);
    const h = base - top;
    const rad = Math.min(4, h, bw / 2);
    const path = h <= 0 ? "" : `<path class="bar" d="M${x},${base} V${top + rad} Q${x},${top} ${x + rad},${top} H${x + bw - rad} Q${x + bw},${top} ${x + bw},${top + rad} V${base} Z"/>`;
    const label = i % 2 === rows.length % 2 ? "" : `<text class="tick" x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${esc(fmtDay(r.date))}</text>`;
    return `<g class="col" data-i="${i}">${path}<rect class="hit" x="${L + i * band}" y="${T}" width="${band}" height="${H - T - B}"/>${label}</g>`;
  }).join("");
  return `<div class="chart" id="${id}">
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(key)} per day, last ${rows.length} days">${grid}
      <line class="axis" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>${bars}</svg>
    <div class="tip" hidden></div></div>`;
}

function bindChart(el, rows, key, fmt, label) {
  const tip = el.querySelector(".tip");
  el.querySelectorAll(".col").forEach((g) => {
    const show = () => {
      const r = rows[Number(g.dataset.i)];
      tip.innerHTML = `<span>${esc(fmtDay(r.date))}</span><strong>${esc(fmt(r[key]))}</strong> ${esc(label)}`;
      tip.hidden = false;
      const box = el.getBoundingClientRect(), b = g.getBoundingClientRect();
      tip.style.left = `${Math.min(Math.max(b.left - box.left + b.width / 2, 60), box.width - 60)}px`;
      el.querySelectorAll(".col").forEach((o) => o.classList.toggle("dim", o !== g));
    };
    g.addEventListener("mouseenter", show);
    g.addEventListener("click", show);
  });
  el.addEventListener("mouseleave", () => {
    tip.hidden = true;
    el.querySelectorAll(".col").forEach((o) => o.classList.remove("dim"));
  });
}

function sparkline(values, label) {
  if (!values || values.length < 2) return "";
  const max = Math.max(...values, 1), W = 100, H = 28, pad = 3;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * W, H - pad - (v / max) * (H - pad * 2)]);
  const [lx, ly] = pts[pts.length - 1];
  // The line stretches to the tile; the end dot is a separate element so it stays round.
  return `<div class="spark-wrap" role="img" aria-label="${esc(label)}"><svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <polyline points="${pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")}"/></svg><span class="spark-dot" data-top="${((ly / H) * 100).toFixed(1)}"></span></div>`;
}

function statTile(label, value, sub = "", hero = false, spark = "") {
  const num = Number(String(value).replace(/[^\d.-]/g, ""));
  return `<div class="stat ${hero ? "hero" : ""}"><div class="label">${esc(label)}</div><div class="value" ${Number.isFinite(num) && num > 0 ? `data-count="${num}"` : ""}>${esc(value)}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}${spark}</div>`;
}

async function renderAdmin() {
  const view = document.getElementById("view");
  delete view.dataset.layout;
  view.innerHTML = `<div class="boot"><div class="spinner"></div></div>`;
  let st;
  try {
    st = await api("/api/admin/stats");
  } catch (err) {
    view.innerHTML = errorBox(err.message);
    return;
  }
  if (state.view !== "admin") return;
  const margin = st.revenue.mrr_estimate_usd - st.cost.last_30d_usd;
  view.innerHTML = `
    <div class="composer-head"><h1>Owner dashboard</h1>
      <p>How Boardroom is doing. Costs are estimates from API token usage${st.engine === "demo" ? " (demo mode makes no API calls, so costs read $0)" : ""}.</p></div>
    <div class="kpis">
      ${statTile("Estimated monthly revenue", fmtUsd(st.revenue.mrr_estimate_usd, 0), `${fmtInt(st.users.pro)} Pro × ${fmtUsd(st.revenue.pro_price_usd, 0)}`, true)}
      ${statTile("Users", fmtInt(st.users.total), `${fmtInt(st.users.new_7d)} new · ${fmtInt(st.users.active_7d)} active this week`, false, sparkline(st.daily.map((d) => d.signups), "Sign-ups per day, last 14 days"))}
      ${statTile("Meetings", fmtInt(st.meetings.last_7d), `last 7 days · ${fmtInt(st.meetings.today)} today`, false, sparkline(st.daily.map((d) => d.meetings), "Meetings per day, last 14 days"))}
      ${statTile("Failure rate", fmtPct(st.meetings.failure_rate_7d), "last 7 days")}
      ${statTile("API cost", fmtUsd(st.cost.last_30d_usd), "last 30 days", false, sparkline(st.daily.map((d) => d.cost_usd), "API cost per day, last 14 days"))}
      ${statTile("Cost per meeting", fmtUsd(st.cost.avg_per_meeting_usd, 3), "average, finished meetings")}
      ${statTile("Revenue minus API cost", fmtUsd(margin, 0), "monthly estimate vs last 30 days")}
      ${statTile("Shared verdicts", fmtInt(st.meetings.shared), "public links, all time")}
      ${(() => {
        const o = st.outcomes, rated = o.great + o.mixed + o.bad;
        return statTile("Decisions that went well", rated ? fmtPct(o.great / rated) : "—", rated ? `${fmtInt(rated)} outcome${rated === 1 ? "" : "s"} reported` : "no outcomes reported yet");
      })()}
    </div>
    <div class="charts">
      <section class="card chart-card"><h2>Meetings per day</h2><p class="chart-sub">Last 14 days</p>${columnChart("ch-meetings", st.daily, "meetings", fmtInt)}</section>
      <section class="card chart-card"><h2>API cost per day</h2><p class="chart-sub">Last 14 days, estimated</p>${columnChart("ch-cost", st.daily, "cost_usd", (v) => fmtUsd(v, v > 0 && v < 10 ? 2 : 0))}</section>
    </div>
    <details class="table-view"><summary>Show as table</summary>
      <table><thead><tr><th>Day</th><th>Sign-ups</th><th>Meetings</th><th>API cost</th></tr></thead>
      <tbody>${st.daily.slice().reverse().map((d) => `<tr><td>${esc(fmtDay(d.date))}</td><td>${fmtInt(d.signups)}</td><td>${fmtInt(d.meetings)}</td><td>${fmtUsd(d.cost_usd, 3)}</td></tr>`).join("")}</tbody></table>
    </details>`;
  bindChart(view.querySelector("#ch-meetings"), st.daily, "meetings", fmtInt, "meetings");
  countUp(view);
  bindChart(view.querySelector("#ch-cost"), st.daily, "cost_usd", (v) => fmtUsd(v, 3), "API cost");
}

/* ---------- public shared view ------------------------------------------ */

async function renderShared(token, sample = false) {
  animScope = sample ? "sample" : `s-${token}`;
  let m;
  try {
    m = await api(sample ? "/api/sample" : `/api/shared/${encodeURIComponent(token)}`);
  } catch (err) {
    $app.innerHTML = `<div class="public"><header class="public-bar"><a class="brand" href="/"><img src="/static/favicon.svg" alt=""> Boardroom</a></header>
      <main class="main"><div class="container">${emptyState("This verdict isn't shared anymore", err.message, "Convene your own board", "/")}</div></main></div>`;
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
        ${sample ? `<div class="demo-banner"><span class="badge">Sample</span>This is an example meeting. Yours will be about your own decision, with live research from the Analyst.</div>` : ""}
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
  animateNew($app);
  countFresh($app);
  clampLong($app);
}

function meetingSkeleton() {
  const card = `<div class="card sk-card"><div class="sk-row"><i class="sk sk-av"></i><div><i class="sk sk-line w40"></i><i class="sk sk-line w25"></i></div></div><i class="sk sk-line"></i><i class="sk sk-line w90"></i><i class="sk sk-line w70"></i></div>`;
  return `<div class="sk-page" aria-busy="true" aria-label="Loading meeting"><i class="sk sk-line w20"></i><i class="sk sk-title"></i><i class="sk sk-title w60"></i>
    <div class="grid sk-grid">${card.repeat(4)}</div></div>`;
}

/* If the verdict lands while you're in another tab, say so in the tab title. */
function tabAlert(text) {
  if (!document.hidden) return;
  const original = document.title;
  document.title = `${text} · Boardroom`;
  const restore = () => { if (!document.hidden) { document.title = original; document.removeEventListener("visibilitychange", restore); } };
  document.addEventListener("visibilitychange", restore);
}

/* Numbers that count up into place. */
function countUp(root) {
  if (reducedMotion()) return;
  root.querySelectorAll("[data-count]").forEach((el) => {
    if (el.dataset.counted) return;
    el.dataset.counted = "1";
    const target = Number(el.dataset.count), final = el.textContent;
    if (!Number.isFinite(target) || target <= 0) return;
    const fmt = (v) => final.replace(/[\d,]+(\.\d+)?/, (num) => {
      const decimals = (num.split(".")[1] || "").length;
      return v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    });
    const start = performance.now(), dur = 900;
    const tick = (t) => {
      const k = Math.min(1, (t - start) / dur), eased = 1 - Math.pow(1 - k, 3);
      el.textContent = k < 1 ? fmt(target * eased) : final;
      if (k < 1) requestAnimationFrame(tick);
    };
    el.textContent = fmt(0);
    requestAnimationFrame(tick);
  });
}

/* Count up only on a verdict's first appearance, not when the view re-renders. */
function countFresh(root) {
  const v = root.querySelector(".verdict.enter");
  if (v && (v.style.getPropertyValue("--since") || "0ms") === "0ms") countUp(v);
}

/* ---------- delight & polish --------------------------------------------- */

const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/* The empty question box types out example questions, one after another. */
let placeholderTimer = null;
function typePlaceholder(q) {
  clearTimeout(placeholderTimer);
  if (reducedMotion()) return;
  let n = 0, i = 0;
  const step = () => {
    if (!q.isConnected) return;
    if (q.value) { placeholderTimer = setTimeout(step, 1500); return; }  // they're typing: wait
    const text = EXAMPLES[n % EXAMPLES.length];
    i += 1;
    q.setAttribute("placeholder", text.slice(0, i));
    if (i < text.length) { placeholderTimer = setTimeout(step, 38); return; }
    placeholderTimer = setTimeout(() => { n += 1; i = 0; step(); }, 2600);
  };
  placeholderTimer = setTimeout(step, 900);
}

/* Fold very long remarks behind "Read more". */
function clampLong(root) {
  if (!root) return;
  root.querySelectorAll(".advisor-card .body.prose:not([data-clamp-checked])").forEach((body) => {
    if (body.classList.contains("caret")) return;  // still streaming
    body.dataset.clampChecked = "1";
    if (body.scrollHeight < 300) return;
    body.classList.add("clamped");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "link read-more";
    btn.setAttribute("aria-expanded", "false");
    btn.textContent = "Read more";
    btn.addEventListener("click", () => {
      const open = !body.classList.toggle("clamped");
      btn.textContent = open ? "Show less" : "Read more";
      btn.setAttribute("aria-expanded", String(open));
    });
    body.after(btn);
  });
}

/* A short burst of confetti, for finishing a whole plan. */
function confetti() {
  if (reducedMotion()) return;
  const canvas = document.createElement("canvas");
  canvas.className = "confetti";
  canvas.setAttribute("aria-hidden", "true");
  const dpr = devicePixelRatio || 1;
  canvas.width = innerWidth * dpr; canvas.height = innerHeight * dpr;
  document.body.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const colors = ["#c9a96e", "#3b82f6", "#ef4444", "#f59e0b", "#10b981", "#8b5cf6"];
  const parts = Array.from({ length: 140 }, () => ({
    x: innerWidth / 2 + (Math.random() - 0.5) * 140, y: innerHeight * 0.55,
    vx: (Math.random() - 0.5) * 13, vy: -Math.random() * 15 - 6,
    w: 6 + Math.random() * 6, h: 3 + Math.random() * 4, r: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.35,
    c: colors[Math.floor(Math.random() * colors.length)],
  }));
  const start = performance.now();
  const frame = (t) => {
    const age = (t - start) / 1000;
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    for (const p of parts) {
      p.vy += 0.42; p.vx *= 0.99; p.x += p.vx; p.y += p.vy; p.r += p.vr;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r);
      ctx.globalAlpha = Math.max(0, 1 - age / 2.2);
      ctx.fillStyle = p.c; ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); ctx.restore();
    }
    if (age < 2.3) requestAnimationFrame(frame); else canvas.remove();
  };
  requestAnimationFrame(frame);
}

/* Three quick slides for brand-new accounts. */
function showTour() {
  try { if (localStorage.getItem("toured")) return; localStorage.setItem("toured", "1"); } catch (_) { /* fine */ }
  const by = Object.fromEntries(state.config.board.map((a) => [a.key, a]));
  const av = (k) => `<span class="avatar" data-c="${by[k].color}">${avatarInner(by[k])}</span>`;
  const slides = [
    { title: "Meet your board", body: "Four specialists look at every decision from a different angle: the facts, the risks, the options and the plan.", art: `<div class="tour-art">${["analyst", "skeptic", "strategist", "operator"].map(av).join("")}</div>` },
    { title: "They debate. The Chair decides.", body: "Watch them weigh in live. Then the Chair hands you a verdict, a confidence score and the options compared.", art: `<div class="tour-art">${av("chair")}<div class="vis-ring"><b>78%</b></div></div>` },
    { title: "A plan you'll actually follow", body: "Tick off steps as you go. On the review date we'll nudge you to check back, and you can ask any advisor a follow-up.", art: `<div class="tour-art vis-verdict"><ul><li><span class="lp-tick">${ICON.check}</span><span></span></li><li><span class="lp-tick">${ICON.check}</span><span></span></li><li class="open"><i></i><span></span></li></ul></div>` },
  ];
  let i = 0;
  const back = document.createElement("div");
  back.className = "modal-back";
  const close = openModal(back);
  const paint = () => {
    const sl = slides[i];
    back.innerHTML = `<div class="modal tour" role="dialog" aria-modal="true" aria-labelledby="tour-title">
      ${sl.art}
      <h2 id="tour-title">${sl.title}</h2>
      <p>${sl.body}</p>
      <div class="tour-foot">
        <div class="dots" aria-hidden="true">${slides.map((_, k) => `<i class="${k === i ? "on" : ""}"></i>`).join("")}</div>
        <span class="sr-only">Step ${i + 1} of ${slides.length}</span>
        <button class="btn btn-ghost" id="tour-skip">${i === slides.length - 1 ? "Close" : "Skip"}</button>
        <button class="btn btn-primary" id="tour-next">${i === slides.length - 1 ? "Convene my first board" : "Next"}</button>
      </div></div>`;
    applyStyles(back);
    back.querySelector("#tour-skip").addEventListener("click", close);
    back.querySelector("#tour-next").addEventListener("click", () => {
      if (i < slides.length - 1) { i += 1; paint(); return; }
      close();
      setTimeout(() => document.getElementById("question")?.focus(), 50);
    });
    back.querySelector("#tour-next").focus();
  };
  paint();
}

/* ---------- keyboard shortcuts ------------------------------------------- */

const isTyping = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
const MOD = navigator.platform.includes("Mac") ? "⌘" : "Ctrl";

function showShortcuts() {
  if (document.querySelector(".shortcuts")) return;
  const rows = [
    [[MOD, "K"], "Command palette: jump to a meeting or run an action"],
    [["N"], "New meeting"],
    [["/"], "Search your meetings"],
    [[MOD, "↵"], "Convene the board (from the question box)"],
    [["T"], "Switch light / dark theme"],
    [["?"], "Show these shortcuts"],
    [["Esc"], "Close any dialog"],
  ];
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal shortcuts" role="dialog" aria-modal="true" aria-labelledby="sc-title">
    <h2 id="sc-title">${ICON.keyboard} Keyboard shortcuts</h2>
    <dl>${rows.map(([keys, what]) => `<div><dt>${keys.map((k) => `<kbd>${esc(k)}</kbd>`).join("")}</dt><dd>${esc(what)}</dd></div>`).join("")}</dl>
    <div class="actions"><button class="btn" id="sc-close">Done</button></div></div>`;
  const close = openModal(back);
  back.querySelector("#sc-close").addEventListener("click", close);
  back.querySelector("#sc-close").focus();
}

document.addEventListener("keydown", (e) => {
  if (!state.user || e.metaKey || e.ctrlKey || e.altKey || isTyping(document.activeElement) || document.querySelector(".modal-back")) return;
  if (e.key === "?") { e.preventDefault(); showShortcuts(); }
  else if (e.key === "n" || e.key === "N") { e.preventDefault(); location.hash = "#/new"; }
  else if (e.key === "/") {
    const search = document.getElementById("search");
    if (search) { e.preventDefault(); if (innerWidth <= 860) document.getElementById("shell")?.classList.add("nav-open"); search.focus(); }
  } else if (e.key === "t" || e.key === "T") { e.preventDefault(); toggleTheme(); }
});

/* ---------- verdict pill ---------------------------------------------------- */

/* If the verdict lands below the fold while you're reading, offer a shortcut to it. */
function verdictPill() {
  const target = document.querySelector(".verdict");
  if (!target || document.getElementById("verdict-pill")) return;
  const rect = target.getBoundingClientRect();
  if (rect.top < innerHeight - 80) return;  // already on screen
  const pill = document.createElement("button");
  pill.id = "verdict-pill";
  pill.type = "button";
  pill.innerHTML = `<span class="dot"></span>The verdict is in ${ICON.arrowDown}`;
  document.body.appendChild(pill);
  const remove = () => { pill.classList.add("leaving"); setTimeout(() => pill.remove(), 250); io.disconnect(); window.removeEventListener("hashchange", remove); };
  const io = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) remove(); }, { threshold: 0.15 });
  io.observe(target);
  pill.addEventListener("click", () => { document.querySelector(".verdict")?.scrollIntoView({ behavior: "smooth", block: "start" }); remove(); });
  window.addEventListener("hashchange", remove);
}

/* ---------- command palette -------------------------------------------------- */

function paletteItems() {
  const items = [
    { group: "Actions", label: "New meeting", hint: "Start fresh", icon: ICON_PLUS, run: () => { location.hash = "#/new"; } },
    { group: "Actions", label: "Switch theme", hint: "Light / dark", icon: ICON.moon, run: toggleTheme },
    { group: "Actions", label: "Invite friends", hint: "Get bonus meetings", icon: ICON.share, run: showInvite },
    { group: "Actions", label: "Account settings", hint: "Password, emails, data", icon: ICON.gear, run: showSettings },
    { group: "Actions", label: "Keyboard shortcuts", hint: "Press ?", icon: ICON.keyboard, run: showShortcuts },
    ...ACCENTS.map(([k, label]) => ({ group: "Appearance", label: `Accent color: ${label}`, hint: currentAccent() === k ? "Current" : "", icon: `<span class="pal-dot pal-${k}"></span>`, run: () => setAccent(k) })),
  ];
  if (state.user?.is_admin) items.push({ group: "Actions", label: "Owner dashboard", hint: "Revenue, usage, costs", icon: ICON.bolt, run: () => { location.hash = "#/admin"; } });
  if (state.user && state.user.usage.plan !== "pro" && !state.config.demo) items.push({ group: "Actions", label: "Upgrade to Pro", hint: state.config.pro_price, icon: ICON.bolt, run: showUpgrade });
  for (const m of state.meetings) {
    items.push({ group: "Meetings", label: m.headline || m.question, hint: m.headline ? m.question : timeAgo(m.created_at), icon: ICON.doc, run: () => { location.hash = `#/m/${m.id}`; } });
  }
  return items;
}

function openPalette() {
  if (!state.user || document.querySelector(".palette")) return;
  const all = paletteItems();
  const back = document.createElement("div");
  back.className = "modal-back palette-back";
  back.innerHTML = `
    <div class="palette" role="dialog" aria-modal="true" aria-label="Command palette">
      <div class="palette-search">${ICON.search}
        <label class="sr-only" for="palette-q">Search meetings and actions</label>
        <input id="palette-q" autocomplete="off" placeholder="Search meetings or type a command…" role="combobox" aria-expanded="true" aria-controls="palette-list">
        <span class="kbd">esc</span>
      </div>
      <ul class="palette-list" id="palette-list" role="listbox"></ul>
      <div class="palette-foot"><span><span class="kbd">↑</span><span class="kbd">↓</span> to move</span><span><span class="kbd">↵</span> to open</span></div>
    </div>`;
  const close = openModal(back);
  const input = back.querySelector("#palette-q");
  const list = back.querySelector("#palette-list");
  let shown = all, active = 0;
  const paint = () => {
    const q = input.value.trim().toLowerCase();
    const words = q.split(/\s+/).filter(Boolean);
    shown = all.filter((it) => words.every((w) => `${it.label} ${it.hint}`.toLowerCase().includes(w))).slice(0, 30);
    active = Math.min(active, Math.max(0, shown.length - 1));
    let group = "";
    list.innerHTML = shown.length ? shown.map((it, i) => {
      const head = it.group !== group ? `<li class="palette-group" role="presentation">${esc(it.group)}</li>` : "";
      group = it.group;
      return `${head}<li role="option" id="pal-${i}" data-i="${i}" aria-selected="${i === active}" class="${i === active ? "active" : ""}">
        <span class="pi">${it.icon}</span><span class="pl">${esc(it.label)}</span><span class="ph">${esc(it.hint || "")}</span></li>`;
    }).join("") : `<li class="palette-empty">Nothing matches “${esc(input.value)}”.</li>`;
    input.setAttribute("aria-activedescendant", shown.length ? `pal-${active}` : "");
    list.querySelector(".active")?.scrollIntoView({ block: "nearest" });
  };
  const run = (i) => { const it = shown[i]; if (!it) return; close(); setTimeout(it.run, 0); };
  input.addEventListener("input", () => { active = 0; paint(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); active = (active + 1) % Math.max(1, shown.length); paint(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = (active - 1 + shown.length) % Math.max(1, shown.length); paint(); }
    else if (e.key === "Enter") { e.preventDefault(); run(active); }
  });
  list.addEventListener("mousemove", (e) => {
    const li = e.target.closest("[data-i]");
    if (li && Number(li.dataset.i) !== active) { active = Number(li.dataset.i); paint(); }
  });
  list.addEventListener("click", (e) => { const li = e.target.closest("[data-i]"); if (li) run(Number(li.dataset.i)); });
  paint();
  input.focus();
}

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k" && state.user) {
    e.preventDefault();
    const open = document.querySelector(".palette-back");
    if (open) open.closeModal(); else openPalette();
  }
});

/* ---------- boot ---------------------------------------------------------- */

async function boot() {
  initTheme();
  const shared = location.pathname.match(/^\/s\/([\w-]+)\/?$/) || location.hash.match(/^#\/s\/([\w-]+)/);
  try {
    state.config = await api("/api/config");
  } catch (_) {
    $app.innerHTML = `<div class="boot"><p>Boardroom is unavailable right now. Please refresh in a moment.</p></div>`;
    return;
  }
  if (shared) { renderShared(shared[1]); return; }
  if (location.hash === "#/sample") { renderShared(null, true); return; }
  const reset = location.hash.match(/^#\/reset\/([\w-]+)/);
  if (reset) { renderReset(reset[1]); return; }
  try {
    state.user = await api("/api/me");
  } catch (_) {
    state.user = null;
  }
  if (state.user) await enterApp();
  else renderLanding(location.hash === "#/login" ? "login" : "signup");
}

boot();
