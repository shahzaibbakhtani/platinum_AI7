"""
================================================================================
README — UMB Corporate Actions Recommendation Copilot (Web UI Launcher)
================================================================================

WHAT THIS SCRIPT DOES
----------------------
Python launcher for the prototype's web interface. It serves the
self-contained HTML/JS page from a local server and opens it in your
default browser -- one file to run, one command.

If a GEMINI_API_KEY environment variable is set in the terminal you run
this from, the launcher passes it into the page automatically so it's
pre-filled in the API key field (still fully editable in the browser).
If no environment variable is set, the field is simply left blank for
you to paste a key into directly in the page -- either way works.

The AI interaction (Gemini API call, system prompt matching UMB-SPEC-01,
structured output schema, and the code-level Heartland escalation
mitigation from Section 6) happens in the generated page's JavaScript,
including automatic retry-with-backoff if Google's free tier returns a
temporary 503/429 "high demand" response. This script's only job is to
serve that page.

The interface also implements Section 4 (User Interaction Flow) step 3's
"clear action buttons (Accept / Override / Request Clarification)"
directly, and a running session-activity view showing the confidence
score of every analysis run so far in the session.

HOW TO RUN
----------
Option A -- no key pre-filled, paste it in the browser:
    python launch_ui.py

Option B -- pre-fill the key from your terminal session:
    PowerShell:  $env:GEMINI_API_KEY="your_key_here"
                 python launch_ui.py
    CMD:         set GEMINI_API_KEY=your_key_here
                 python launch_ui.py

Either way, your browser opens automatically to the Copilot interface.
Click "Load sample scenario" to try a test case, or type your own
announcement and account details, then click "Analyze announcement".

WHAT A PRODUCTION VERSION WOULD REQUIRE DIFFERENTLY
-----------------------------------------------------
- A backend proxy: the browser currently calls Google directly with a
  user-supplied key, fine for a local demo but not for production --
  a server-side proxy should sit between the UI and the model so the
  API key and account data never touch the client directly (per
  Section 6 and Nazifa's B/B/P first-30-days API gateway action item).
- Real RAG against UMB Fund Services custody records instead of
  manually entered text.
- The Accept / Override / Request Clarification actions here are
  simulated confirmations for the demo; production would write these
  to a real audit log and push Accepted elections back into XSP/eTran,
  per Section 4 step 5.
- Verified quoting, full audit logging, and AuthN/AuthZ, as noted in
  the terminal-based prototype (corporate_actions_copilot.py).

TOOLS USED
----------
Scaffolded with the help of Claude (Anthropic), per the assignment's
pre-work note permitting AI coding assistants.
================================================================================
"""

import http.server
import socketserver
import threading
import webbrowser
import sys
import os
import json

PORT = 8765

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>UMB Corporate Actions Copilot</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{
    --crimson:#96151D;
    --crimson-deep:#6E0F16;
    --ink:#14110F;
    --ink-soft:#5C5652;
    --paper:#F5F3F0;
    --paper-panel:#FFFFFF;
    --line:#E4E0DA;
    --cobalt:#1B5FAE;
    --cobalt-soft:#E7EFF8;
    --good:#1E6B45;
    --good-bg:#E4F1EA;
    --risk:#96151D;
    --risk-bg:#FBEAEB;
  }
  *{box-sizing:border-box;}
  html,body{margin:0;padding:0;background:var(--paper);color:var(--ink);
    font-family:'Inter',sans-serif;}
  h1,h2,h3{font-family:'Inter',sans-serif;font-weight:800;margin:0;letter-spacing:-.01em;}
  .mono{font-family:'IBM Plex Mono',monospace;}

  header{
    position:relative;
    padding:38px 40px 34px;
    background:var(--ink);
    color:#fff;
    display:flex;justify-content:space-between;align-items:flex-end;
    flex-wrap:wrap;gap:14px;
    overflow:hidden;
    min-height:150px;
  }
  header::before{
    content:"";position:absolute;top:0;right:0;bottom:0;width:46%;
    background:var(--crimson);
    clip-path:polygon(28% 0, 100% 0, 100% 100%, 0% 100%);
    opacity:.94;
  }
  header .wordmark{
    position:absolute;top:50%;right:38px;z-index:1;
    transform:translateY(-50%);
    font-family:'Inter',sans-serif;font-weight:900;font-size:118px;letter-spacing:-.04em;
    color:rgba(255,255,255,.16);
    line-height:1;
    user-select:none;
    pointer-events:none;
  }
  @media (max-width:760px){ header .wordmark{display:none;} }
  header .ticker{display:none;}
  header .title{position:relative;z-index:1;}
  header .title h1{font-size:32px;letter-spacing:-.02em;color:#fff;font-weight:900;}
  header .title p{margin:9px 0 0;color:#D9D5D0;font-size:14.5px;font-weight:500;}
  header .tag{
    position:relative;z-index:1;
    font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:#fff;
    border:1px solid rgba(255,255,255,.35);padding:7px 12px;border-radius:20px;
    background:rgba(0,0,0,.15);letter-spacing:.02em;
  }

  main{
    display:grid;grid-template-columns:minmax(320px,420px) 1fr;
    gap:0;min-height:calc(100vh - 108px);
  }
  @media (max-width:900px){ main{grid-template-columns:1fr;} }

  .panel{padding:32px 40px;}
  .input-panel{border-right:1px solid var(--line);}

  label{display:block;font-size:13px;color:var(--ink-soft);margin:20px 0 8px;font-weight:500;}
  label:first-of-type{margin-top:0;}
  textarea,input[type=password],input[type=text]{
    width:100%;border:1px solid var(--line);border-radius:4px;background:var(--paper-panel);
    padding:12px 13px;font-family:'Inter',sans-serif;font-size:14px;color:var(--ink);
    resize:vertical;line-height:1.5;
  }
  textarea:focus,input:focus{outline:2px solid var(--cobalt);outline-offset:1px;border-color:var(--cobalt);}
  textarea#announcement{height:120px;}
  textarea#account{height:100px;}

  .examples{display:flex;gap:8px;margin-bottom:4px;flex-wrap:wrap;}
  .examples button{
    font-size:12.5px;padding:8px 15px;border-radius:20px;border:1.5px solid var(--line);
    background:var(--paper-panel);color:var(--ink-soft);cursor:pointer;font-family:'Inter',sans-serif;
    font-weight:600;
  }
  .examples button:hover{border-color:var(--crimson);color:var(--crimson);}

  .run-btn{
    margin-top:26px;width:100%;padding:15px;border:none;border-radius:30px;
    background:var(--crimson);color:#fff;font-size:15px;font-weight:700;
    font-family:'Inter',sans-serif;cursor:pointer;letter-spacing:.1px;
    transition:background .15s ease;
  }
  .run-btn:hover{background:var(--crimson-deep);}
  .run-btn:disabled{background:#C9C4BE;cursor:progress;}

  .key-hint{font-size:12px;color:var(--ink-soft);margin-top:8px;line-height:1.5;}
  .key-preset-note{font-size:12px;color:var(--good);margin-top:8px;}

  /* --- session activity chart --- */
  .session{margin-top:30px;padding-top:22px;border-top:1px solid var(--line);}
  .session h3{font-size:13px;color:var(--ink-soft);font-weight:500;margin-bottom:12px;}
  .session-empty{font-size:12.5px;color:var(--ink-soft);}
  .session-row{display:flex;align-items:center;gap:10px;margin-bottom:9px;}
  .session-row .sess-label{font-size:11.5px;color:var(--ink-soft);width:118px;flex-shrink:0;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .session-row .sess-track{flex:1;height:8px;background:var(--line);border-radius:4px;overflow:hidden;}
  .session-row .sess-fill{height:100%;background:var(--cobalt);}
  .session-row .sess-fill.low{background:var(--risk);}
  .session-row .sess-val{font-size:11.5px;font-family:'IBM Plex Mono',monospace;color:var(--ink-soft);width:32px;text-align:right;}

  .output-panel{background:var(--paper);}
  .empty-state{
    height:100%;min-height:400px;display:flex;flex-direction:column;
    align-items:flex-start;justify-content:center;color:var(--ink-soft);
    max-width:380px;
  }
  .empty-state h2{font-size:19px;color:var(--ink);margin-bottom:10px;}
  .empty-state p{font-size:14px;line-height:1.6;}

  .result{display:none;}
  .result.show{display:block;}

  .result-head{
    display:flex;justify-content:space-between;align-items:flex-start;
    padding-bottom:20px;border-bottom:1px solid var(--line);margin-bottom:22px;flex-wrap:wrap;gap:14px;
  }
  .result-head h2{font-size:24px;margin-bottom:6px;}
  .result-head .event-type{color:var(--ink-soft);font-size:13.5px;font-weight:500;}

  .status-badge{
    display:inline-flex;align-items:center;gap:7px;padding:9px 16px;border-radius:20px;
    font-size:13px;font-weight:700;white-space:nowrap;
  }
  .status-badge.ready{background:var(--good-bg);color:var(--good);}
  .status-badge.escalate{background:var(--risk-bg);color:var(--risk);}
  .status-badge .dot{width:8px;height:8px;border-radius:50%;background:currentColor;}

  .metric-row{display:flex;gap:36px;margin-bottom:26px;flex-wrap:wrap;align-items:center;}

  .gauge-wrap{display:flex;align-items:center;gap:16px;}
  .gauge-wrap .gauge-num{font-size:26px;font-family:'IBM Plex Mono',monospace;}
  .gauge-wrap .gauge-label{font-size:12px;color:var(--ink-soft);margin-top:2px;}

  .section{margin-bottom:22px;}
  .section h3{font-size:13px;color:var(--ink-soft);font-weight:500;margin-bottom:8px;}
  .section p{margin:0;font-size:14.5px;line-height:1.65;}

  blockquote{
    margin:0;padding:14px 16px;background:var(--cobalt-soft);border-left:3px solid var(--cobalt);
    font-family:'IBM Plex Mono',monospace;font-size:13px;line-height:1.6;color:#153E73;border-radius:12px;
  }

  .escalation-box{
    background:var(--risk-bg);border-left:3px solid var(--risk);padding:14px 16px;border-radius:12px;
  }
  .escalation-box p{color:var(--risk);}

  .error-box{
    background:var(--risk-bg);border-left:3px solid var(--risk);padding:16px 18px;border-radius:12px;
    color:var(--risk);font-size:14px;line-height:1.6;white-space:pre-wrap;
  }

  .loading{display:none;align-items:center;gap:10px;color:var(--ink-soft);font-size:14px;padding:20px 0;}
  .loading.show{display:flex;}
  .spinner{width:16px;height:16px;border:2px solid var(--line);border-top-color:var(--crimson);
    border-radius:50%;animation:spin .8s linear infinite;}
  @keyframes spin{to{transform:rotate(360deg);}}

  .action-row{display:flex;gap:10px;margin-top:28px;padding-top:22px;border-top:1px solid var(--line);flex-wrap:wrap;}
  .action-btn{
    padding:12px 22px;border-radius:24px;font-size:13.5px;font-weight:700;cursor:pointer;
    font-family:'Inter',sans-serif;border:1.5px solid var(--line);background:var(--paper-panel);color:var(--ink);
    transition:all .15s ease;
  }
  .action-btn:hover{border-color:var(--ink);}
  .action-btn.accept{background:var(--crimson);color:#fff;border-color:var(--crimson);}
  .action-btn.accept:hover{background:var(--crimson-deep);}
  .action-btn.accept:disabled{background:#D8D3CD;border-color:#D8D3CD;color:#8A857F;cursor:not-allowed;}
  .action-btn.clarify{color:var(--cobalt);border-color:var(--cobalt);}
  .action-btn.clarify:hover{background:var(--cobalt-soft);}

  .override-form{display:none;margin-top:14px;}
  .override-form.show{display:block;}
  .override-form textarea{height:70px;margin-bottom:10px;}
  .override-form .confirm-btn{
    padding:10px 20px;border-radius:24px;border:none;background:var(--ink);color:#fff;
    font-size:13px;font-weight:700;cursor:pointer;
  }

  .action-confirm{
    margin-top:16px;padding:13px 16px;border-radius:12px;font-size:13.5px;line-height:1.55;
    display:none;
  }
  .action-confirm.show{display:block;}
  .action-confirm.accept{background:var(--good-bg);color:var(--good);}
  .action-confirm.override{background:var(--cobalt-soft);color:#153E73;}
  .action-confirm.clarify{background:var(--risk-bg);color:var(--risk);}
</style>
<script>window.__PRESET_API_KEY__ = "__PY_ENV_KEY__";</script>
</head>
<body>

<header>
  <div class="wordmark" aria-hidden="true">UMB</div>
  <div class="title">
    <h1>Corporate Actions Copilot</h1>
    <p>Institutional Custody &amp; Corporate Trust — Decision Support Prototype</p>
  </div>
  <div class="tag">UMB-PROTO-01 · UMB-SPEC-01</div>
</header>

<main>
  <div class="panel input-panel">
    <label style="margin-top:0;">Load a sample scenario</label>
    <div class="examples">
      <button type="button" onclick="loadExample(1)">Legacy account</button>
      <button type="button" onclick="loadExample(2)">Heartland-converted account</button>
    </div>

    <label for="announcement">Corporate action announcement</label>
    <textarea id="announcement" placeholder="Paste the announcement text here..."></textarea>

    <label for="account">Account holdings &amp; standing instructions</label>
    <textarea id="account" placeholder="Account details, position size, and standing instructions..."></textarea>

    <label for="apikey">Gemini API key</label>
    <input type="password" id="apikey" placeholder="Paste your API key">
    <p class="key-hint" id="keyHint">Your key is used only in this browser session to call Google's API directly. It is never saved, logged, or sent anywhere else.</p>

    <button class="run-btn" id="runBtn" onclick="analyze()">Analyze announcement</button>

    <div class="session">
      <h3>Session activity</h3>
      <div id="sessionList"><p class="session-empty">No analyses run yet this session.</p></div>
    </div>
  </div>

  <div class="panel output-panel">
    <div class="empty-state" id="emptyState">
      <h2>Awaiting input</h2>
      <p>Load a sample scenario or paste your own announcement and account details, then analyze to see the recommendation the way an analyst would.</p>
    </div>

    <div class="loading" id="loading">
      <div class="spinner"></div>
      <span>Reading the announcement and cross-checking standing instructions…</span>
    </div>

    <div class="result" id="result">
      <div class="result-head">
        <div>
          <h2 id="resElection">—</h2>
          <div class="event-type" id="resEventType">—</div>
        </div>
        <div class="status-badge" id="resStatus"><span class="dot"></span><span id="resStatusText">—</span></div>
      </div>

      <div class="metric-row">
        <div class="gauge-wrap">
          <svg width="64" height="64" viewBox="0 0 64 64">
            <circle cx="32" cy="32" r="27" fill="none" stroke="#DFDACC" stroke-width="7"/>
            <circle id="gaugeCircle" cx="32" cy="32" r="27" fill="none" stroke="#1B5FAE" stroke-width="7"
              stroke-dasharray="169.6" stroke-dashoffset="169.6" stroke-linecap="round"
              transform="rotate(-90 32 32)"/>
          </svg>
          <div>
            <div class="gauge-num"><span id="resConfidence">—</span>%</div>
            <div class="gauge-label">Confidence score</div>
          </div>
        </div>
      </div>

      <div class="section">
        <h3>Rationale</h3>
        <p id="resRationale">—</p>
      </div>

      <div class="section">
        <h3>Supporting quote (verbatim from announcement)</h3>
        <blockquote id="resQuote">—</blockquote>
      </div>

      <div class="section" id="escalationSection" style="display:none;">
        <h3>Escalation reason</h3>
        <div class="escalation-box"><p id="resEscalation">—</p></div>
      </div>

      <div class="action-row">
        <button class="action-btn accept" id="btnAccept" onclick="doAccept()">Accept</button>
        <button class="action-btn" id="btnOverride" onclick="toggleOverride()">Override</button>
        <button class="action-btn clarify" id="btnClarify" onclick="doClarify()">Request clarification</button>
      </div>

      <div class="override-form" id="overrideForm">
        <label style="margin-top:14px;">Override reason</label>
        <textarea id="overrideReason" placeholder="Explain why you're overriding the recommended election..."></textarea>
        <button class="confirm-btn" onclick="confirmOverride()">Log override</button>
      </div>

      <div class="action-confirm" id="actionConfirm"></div>
    </div>

    <div class="result" id="errorResult">
      <div class="error-box" id="errorText"></div>
    </div>
  </div>
</main>

<script>
const SYSTEM_PROMPT = `You are the Corporate Actions Recommendation Copilot for UMB Financial Corporation's Institutional Custody & Corporate Trust team.

Analysts currently read every voluntary corporate action announcement manually and evaluate its terms against each account's specific standing instructions ahead of strict market deadlines. Your job is to do that first pass for them.

For each case you receive ONE corporate action announcement plus ONE account's holdings and standing instructions. You must:

1. Identify the corporate action type and its key terms and deadline.
2. Recommend the specific election this account should make, based ONLY on the standing instructions and holdings provided — never invent information not present in the input.
3. Provide a confidence score from 0 to 100 reflecting how clearly the standing instructions map to this specific event.
4. Write a rationale that includes at least one short VERBATIM quote copied exactly from the announcement text supporting your recommendation. Do not paraphrase the quoted portion.
5. Set escalation_required to true if: the standing instructions are missing, ambiguous, inconsistent with the account type, or if the announcement terms are unclear or unusual enough that a human should review before acting. Otherwise set it to false.
6. If you escalate, explain exactly what a human analyst needs to resolve.

Respond only with the structured JSON fields requested. Do not fabricate deadlines, prices, or account details not present in the input.`;

const RESPONSE_SCHEMA = {
  type: "OBJECT",
  properties: {
    event_type: { type: "STRING" },
    recommended_election: { type: "STRING" },
    confidence_score: { type: "INTEGER" },
    rationale: { type: "STRING" },
    supporting_quote: { type: "STRING" },
    escalation_required: { type: "BOOLEAN" },
    escalation_reason: { type: "STRING" }
  },
  required: ["event_type","recommended_election","confidence_score","rationale",
             "supporting_quote","escalation_required","escalation_reason"]
};

const MODEL = "gemini-3.6-flash";

const examples = {
  1: {
    announcement: `NOTICE OF VOLUNTARY TENDER OFFER — Ridgeline Materials Corp (CUSIP 76582A10). Ridgeline Materials Corp is offering to purchase up to 8,000,000 shares of its common stock at a price of $42.50 per share in cash, representing a 15% premium to the prior closing price. The offer expires at 5:00 PM Eastern Time on November 14, 2026. Shareholders may tender all, some, or none of their shares. Partial tenders will be accepted on a pro-rata basis if the offer is oversubscribed.`,
    account: `Account: UMB-CUST-004471 (legacy UMB institutional account, active since 2011)
Holdings: 50,000 shares of Ridgeline Materials Corp (CUSIP 76582A10)
Standing Instructions: "For voluntary cash tender offers at a premium of 10% or greater to market price, tender 100% of eligible shares unless client contacts custody team directly to override."`
  },
  2: {
    announcement: `NOTICE OF RIGHTS OFFERING — Prairie Grain Cooperative Inc (CUSIP 74019B22). Prairie Grain Cooperative Inc is issuing transferable subscription rights to holders of record as of October 30, 2026, entitling holders to purchase one new common share for every four rights held at a subscription price of $18.00 per share. Rights not exercised by 5:00 PM Eastern Time on December 5, 2026 will expire worthless. Rights may also be sold on the open market prior to expiration.`,
    account: `Account: HRTLND-CUST-002218 (converted from Heartland Financial USA, October 2025)
Holdings: 12,000 shares of Prairie Grain Cooperative Inc (CUSIP 74019B22)
Standing Instructions: [NOT FOUND — record not migrated/standardized during Heartland conversion]`
  }
};

let sessionHistory = [];
let currentResult = null;

function loadExample(n){
  document.getElementById('announcement').value = examples[n].announcement;
  document.getElementById('account').value = examples[n].account;
}

function enforceHeartlandMitigation(result, accountText){
  const isHeartland = /heartland/i.test(accountText);
  const missingInstructions = /not found|missing|unavailable/i.test(accountText);
  if (isHeartland && missingInstructions){
    result.escalation_required = true;
    result.confidence_score = Math.min(result.confidence_score ?? 0, 20);
    const note = "SYSTEM OVERRIDE: Heartland-converted account with missing/non-standard standing instructions — automatically defaulted to low-trust status and escalated per policy, independent of model confidence.";
    result.escalation_reason = `${note} Model's own reason: ${result.escalation_reason || "none given"}`;
  }
  return result;
}

async function callGeminiWithRetry(payload, apiKey, maxAttempts = 3){
  let lastError = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt++){
    const resp = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${apiKey}`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }
    );

    if (resp.status === 503 || resp.status === 429){
      lastError = `API returned ${resp.status} (server busy)`;
      if (attempt < maxAttempts){
        await new Promise(r => setTimeout(r, 3000 * attempt)); // 3s, then 6s
        continue;
      }
      const bodyText = await resp.text();
      throw new Error(`${lastError} — gave up after ${maxAttempts} attempts. Full response: ${bodyText}`);
    }

    if (!resp.ok){
      const bodyText = await resp.text();
      throw new Error(`API returned ${resp.status}: ${bodyText}`);
    }

    return resp; // success
  }
  throw new Error(lastError || "Unknown error");
}

async function analyze(){
  const announcement = document.getElementById('announcement').value.trim();
  const account = document.getElementById('account').value.trim();
  const apiKey = document.getElementById('apikey').value.trim();

  const emptyState = document.getElementById('emptyState');
  const loading = document.getElementById('loading');
  const result = document.getElementById('result');
  const errorResult = document.getElementById('errorResult');
  const runBtn = document.getElementById('runBtn');

  errorResult.classList.remove('show');
  result.classList.remove('show');
  resetActionState();

  if (!announcement || !account){
    showError("Enter both the announcement text and the account context before analyzing.");
    return;
  }
  if (!apiKey){
    showError("Enter your Gemini API key. It's only used for this request, never stored.");
    return;
  }

  emptyState.style.display = 'none';
  loading.classList.add('show');
  runBtn.disabled = true;
  runBtn.textContent = 'Analyzing…';

  const payload = {
    system_instruction: { parts: [{ text: SYSTEM_PROMPT }] },
    contents: [{ role: "user", parts: [{ text:
      `CORPORATE ACTION ANNOUNCEMENT:\n${announcement}\n\nACCOUNT HOLDINGS & STANDING INSTRUCTIONS:\n${account}` }] }],
    generationConfig: {
      responseMimeType: "application/json",
      responseSchema: RESPONSE_SCHEMA,
      temperature: 0.2
    }
  };

  try{
    const resp = await callGeminiWithRetry(payload, apiKey);
    const data = await resp.json();
    const rawText = data.candidates[0].content.parts[0].text;
    let parsed = JSON.parse(rawText);
    parsed = enforceHeartlandMitigation(parsed, account);

    currentResult = parsed;
    renderResult(parsed);
    addToSession(parsed);

  } catch(err){
    showError(`Request failed: ${err.message}\n\n(This is the graceful-failure path — no crash, no invented output. The system retried automatically before showing this.)`);
  } finally {
    loading.classList.remove('show');
    runBtn.disabled = false;
    runBtn.textContent = 'Analyze announcement';
  }
}

function renderResult(r){
  document.getElementById('resElection').textContent = r.recommended_election || '—';
  document.getElementById('resEventType').textContent = r.event_type || '—';
  document.getElementById('resConfidence').textContent = r.confidence_score ?? '—';
  document.getElementById('resRationale').textContent = r.rationale || '—';
  document.getElementById('resQuote').textContent = r.supporting_quote || '—';

  const score = r.confidence_score ?? 0;
  const circumference = 169.6;
  const offset = circumference - (circumference * Math.min(score,100) / 100);
  const circle = document.getElementById('gaugeCircle');
  circle.style.strokeDashoffset = offset;
  circle.setAttribute('stroke', score < 50 ? '#96151D' : '#1B5FAE');

  const badge = document.getElementById('resStatus');
  const badgeText = document.getElementById('resStatusText');
  const escSection = document.getElementById('escalationSection');
  const btnAccept = document.getElementById('btnAccept');

  if (r.escalation_required){
    badge.className = 'status-badge escalate';
    badgeText.textContent = 'Escalate to analyst';
    escSection.style.display = 'block';
    document.getElementById('resEscalation').textContent = r.escalation_reason || '—';
    btnAccept.disabled = true;
    btnAccept.title = 'This item requires escalation — one-click Accept is disabled.';
  } else {
    badge.className = 'status-badge ready';
    badgeText.textContent = 'Ready for one-click review';
    escSection.style.display = 'none';
    btnAccept.disabled = false;
    btnAccept.title = '';
  }

  document.getElementById('result').classList.add('show');
}

function addToSession(r){
  const label = (r.event_type || 'Analysis') + ' #' + (sessionHistory.length + 1);
  sessionHistory.push({ label, confidence: r.confidence_score ?? 0, escalated: !!r.escalation_required });
  renderSession();
}

function renderSession(){
  const el = document.getElementById('sessionList');
  if (sessionHistory.length === 0){
    el.innerHTML = '<p class="session-empty">No analyses run yet this session.</p>';
    return;
  }
  el.innerHTML = sessionHistory.map(item => `
    <div class="session-row">
      <span class="sess-label" title="${item.label}">${item.label}</span>
      <span class="sess-track"><span class="sess-fill${item.confidence < 50 ? ' low' : ''}" style="width:${item.confidence}%"></span></span>
      <span class="sess-val">${item.confidence}%</span>
    </div>
  `).join('');
}

function resetActionState(){
  document.getElementById('overrideForm').classList.remove('show');
  document.getElementById('actionConfirm').classList.remove('show');
  document.getElementById('overrideReason').value = '';
}

function showActionConfirm(kind, message){
  const box = document.getElementById('actionConfirm');
  box.className = `action-confirm show ${kind}`;
  box.textContent = message;
}

function doAccept(){
  if (!currentResult) return;
  showActionConfirm('accept',
    `Approved. Recommendation pushed to XSP/eTran for settlement (simulated — Section 4, step 5: "Copilot does not execute trades directly").`);
}

function toggleOverride(){
  document.getElementById('overrideForm').classList.toggle('show');
}

function confirmOverride(){
  const reason = document.getElementById('overrideReason').value.trim();
  if (!reason){
    showActionConfirm('override', 'Enter an override reason before logging — Section 6 requires written notes on all manual overrides.');
    return;
  }
  showActionConfirm('override', `Override logged: "${reason}" (simulated audit trail entry — Section 6 mitigation for analyst automation bias).`);
  document.getElementById('overrideForm').classList.remove('show');
}

function doClarify(){
  if (!currentResult) return;
  showActionConfirm('clarify',
    'Routed to secondary escalation queue for senior analyst review (simulated — Section 4, step 4).');
}

function showError(msg){
  document.getElementById('emptyState').style.display = 'none';
  const box = document.getElementById('errorResult');
  document.getElementById('errorText').textContent = msg;
  box.classList.add('show');
}

if (typeof window.__PRESET_API_KEY__ === 'string' && window.__PRESET_API_KEY__.length > 0){
  document.getElementById('apikey').value = window.__PRESET_API_KEY__;
  document.getElementById('keyHint').textContent = '';
  const note = document.createElement('p');
  note.className = 'key-preset-note';
  note.textContent = 'Key loaded from your GEMINI_API_KEY environment variable.';
  document.getElementById('keyHint').after(note);
}
</script>

</body>
</html>
"""


def build_page():
    """Injects the terminal's GEMINI_API_KEY (if set) into the page as a
    safely escaped JS string literal."""
    key = os.environ.get("GEMINI_API_KEY", "")
    safe_key = json.dumps(key)
    return HTML_TEMPLATE.replace('"__PY_ENV_KEY__"', safe_key)


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(build_page().encode("utf-8"))

    def log_message(self, format, *args):
        pass  # keep the terminal quiet during the demo


def main():
    if os.environ.get("GEMINI_API_KEY"):
        print("Found GEMINI_API_KEY in this terminal session -- it will be pre-filled in the page.")
    else:
        print("No GEMINI_API_KEY set in this terminal -- paste your key directly into the page instead.")

    try:
        with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
            url = f"http://127.0.0.1:{PORT}"
            print(f"UMB Corporate Actions Copilot is running at {url}")
            print("Opening in your default browser... (Ctrl+C here to stop the server)")
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
            httpd.serve_forever()
    except OSError as e:
        print(f"Could not start the local server on port {PORT}: {e}")
        print("If the port is already in use, close other running instances and try again.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
