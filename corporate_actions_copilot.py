"""
================================================================================
README — UMB Corporate Actions Recommendation Copilot (UMB-PROTO-01)
================================================================================

WHAT THIS PROTOTYPE DEMONSTRATES
---------------------------------
A minimal working demo of the core AI interaction described in UMB-SPEC-01:
an LLM reads one voluntary corporate action announcement, cross-references
it against a specific account's holdings and standing instructions, and
returns a structured election recommendation an Institutional Custody
analyst could act on — instead of the analyst reading and interpreting the
announcement by hand.

Input:  corporate action announcement text + account holdings & standing
        instructions (matches Section 2 "Input Payload" of the spec)
Output: recommended election, confidence score (0-100%), a rationale that
        quotes the announcement verbatim (per the Section 6 hallucination
        mitigation), and a human-escalation flag (matches Section 2
        "Output Response")

This prototype simulates the RAG context-retrieval step (Section 4, step 2)
by passing standing instructions and holdings directly into the prompt as
retrieved context, rather than querying a live vector store. It also
enforces one mitigation from Section 6 in CODE, not just in the prompt:
any Heartland-converted account with missing/non-standard standing
instructions is force-escalated regardless of what the model returns,
matching the "default to low-trust status" mitigation for the Heartland
Data Discrepancy risk.

HOW TO RUN
----------
1. Get a free Gemini API key: https://aistudio.google.com/app/apikey
2. Set it as an environment variable (do NOT paste it into this file):
       macOS/Linux:   export GEMINI_API_KEY="your_key_here"
       Windows CMD:   set GEMINI_API_KEY=your_key_here
   (If you skip this, the script falls back to the placeholder below and
   will print a clear error instead of crashing.)
3. Install the one dependency:
       pip install requests
4. Run:
       python3 corporate_actions_copilot.py

The script runs two sample cases end-to-end with no other setup required:
  Case 1: a legacy UMB account with clear standing instructions
  Case 2: a Heartland-converted account with missing standing instructions
          (demonstrates the forced-escalation edge case)

WHAT A PRODUCTION VERSION WOULD REQUIRE DIFFERENTLY
-----------------------------------------------------
- Real RAG: a vector database of historical precedent + a live query
  against UMB Fund Services custody records and Xcitek XSP/eTran feeds,
  instead of hardcoded sample strings.
- Verified quoting: the "supporting_quote" field would be programmatically
  checked (e.g., substring match) against the source announcement text
  before the Accept button unlocks in the UI, per the Section 6 mitigation
  — this prototype only asks the model to quote verbatim, it does not yet
  verify the quote server-side.
- Auditability: every recommendation, override, and analyst note logged
  to a compliance-grade audit trail (Section 6: "Analyst Automation Bias"
  mitigation calls for randomized spot-checks).
- AuthN/AuthZ, PII/account-number masking before the payload leaves UMB's
  network (per Nazifa's B/B/P first-30-days action item), retries, and
  proper error handling/observability.
- Latency: this script makes one synchronous call; production would need
  to meet the <5 second per-account interactive latency target under load,
  likely via batching for overnight runs as the spec allows.

TOOLS USED
----------
Scaffolded with the help of Claude (Anthropic) based on the completed
UMB-SPEC-01 and UMB-BBP-01 documents, per the assignment's pre-work note
permitting AI coding assistants.
================================================================================
"""

import os
import json
import time
import requests

# --------------------------------------------------------------------------
# API KEY — never hardcode a real key here. Set the GEMINI_API_KEY
# environment variable instead. This placeholder is intentional.
# --------------------------------------------------------------------------
API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_KEY_HERE")
MODEL = "gemini-3.6-flash"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

# --------------------------------------------------------------------------
# SYSTEM PROMPT — derived directly from UMB-SPEC-01 Sections 1, 2, and 6.
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """You are the Corporate Actions Recommendation Copilot for UMB Financial \
Corporation's Institutional Custody & Corporate Trust team.

Analysts currently read every voluntary corporate action announcement manually and \
evaluate its terms against each account's specific standing instructions ahead of strict \
market deadlines. Your job is to do that first pass for them.

For each case you receive ONE corporate action announcement plus ONE account's holdings \
and standing instructions. You must:

1. Identify the corporate action type and its key terms and deadline.
2. Recommend the specific election this account should make, based ONLY on the standing \
instructions and holdings provided — never invent information not present in the input.
3. Provide a confidence score from 0 to 100 reflecting how clearly the standing \
instructions map to this specific event.
4. Write a rationale that includes at least one short VERBATIM quote copied exactly from \
the announcement text supporting your recommendation. Do not paraphrase the quoted portion.
5. Set escalation_required to true if: the standing instructions are missing, ambiguous, \
inconsistent with the account type, or if the announcement terms are unclear or unusual \
enough that a human should review before acting. Otherwise set it to false.
6. If you escalate, explain exactly what a human analyst needs to resolve.

Respond only with the structured JSON fields requested. Do not fabricate deadlines, \
prices, or account details not present in the input."""

# --------------------------------------------------------------------------
# STRUCTURED OUTPUT SCHEMA — matches Section 2 "Output Response"
# --------------------------------------------------------------------------
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "event_type": {"type": "STRING"},
        "recommended_election": {"type": "STRING"},
        "confidence_score": {"type": "INTEGER"},
        "rationale": {"type": "STRING"},
        "supporting_quote": {"type": "STRING"},
        "escalation_required": {"type": "BOOLEAN"},
        "escalation_reason": {"type": "STRING"},
    },
    "required": [
        "event_type",
        "recommended_election",
        "confidence_score",
        "rationale",
        "supporting_quote",
        "escalation_required",
        "escalation_reason",
    ],
}


def call_copilot(announcement_text: str, account_context: str) -> dict:
    """Calls the Gemini API and returns the parsed structured recommendation."""
    user_prompt = (
        f"CORPORATE ACTION ANNOUNCEMENT:\n{announcement_text}\n\n"
        f"ACCOUNT HOLDINGS & STANDING INSTRUCTIONS:\n{account_context}"
    )

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "temperature": 0.2,
        },
    }

    # Gemini's free-tier endpoint occasionally returns 503 (server overloaded)
    # or 429 (rate limited) under normal, non-error conditions. Retry a few
    # times with a short backoff before treating it as a real failure.
    max_attempts = 3
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(
                f"{API_URL}?key={API_KEY}",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=30,
            )
            if resp.status_code in (503, 429) and attempt < max_attempts:
                time.sleep(3 * attempt)  # 3s, then 6s
                continue
            if resp.status_code >= 400:
                # Show Google's actual error body instead of a generic message
                return {"error": f"API returned {resp.status_code}: {resp.text}"}
            data = resp.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(raw_text)

        except requests.exceptions.RequestException as e:
            last_error = f"API request failed: {e}"
            if attempt < max_attempts:
                time.sleep(3 * attempt)
                continue
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return {"error": f"Could not parse model response: {e}"}

    return {"error": f"{last_error} (gave up after {max_attempts} attempts — "
                      f"this is likely a temporary Gemini free-tier capacity "
                      f"issue, try again in a minute)"}


def enforce_heartland_mitigation(result: dict, is_heartland_converted: bool,
                                  standing_instructions_missing: bool) -> dict:
    """
    Code-level enforcement of the Section 6 mitigation for 'Heartland Data
    Discrepancy': Heartland-converted accounts with missing/non-standard
    standing instructions are force-escalated regardless of model output.
    """
    if is_heartland_converted and standing_instructions_missing:
        result["escalation_required"] = True
        result["confidence_score"] = min(result.get("confidence_score", 0), 20)
        note = ("SYSTEM OVERRIDE: Heartland-converted account with missing/non-standard "
                "standing instructions — automatically defaulted to low-trust status "
                "and escalated per policy, independent of model confidence.")
        result["escalation_reason"] = (
            f"{note} Model's own reason: {result.get('escalation_reason', 'none given')}"
        )
    return result


def display_result(case_label: str, result: dict):
    """Formats and prints the recommendation the way an analyst would see it —
    not raw JSON."""
    print("\n" + "=" * 78)
    print(f"CASE: {case_label}")
    print("=" * 78)

    if "error" in result:
        print(f"⚠️  {result['error']}")
        print("(This is the graceful-failure path — no crash, no hallucinated output.)")
        return

    escalation = result.get("escalation_required", False)
    flag = "🔴 ESCALATE TO ANALYST" if escalation else "🟢 READY FOR ONE-CLICK REVIEW"

    print(f"Event Type:           {result.get('event_type', 'N/A')}")
    print(f"Recommended Election: {result.get('recommended_election', 'N/A')}")
    print(f"Confidence Score:     {result.get('confidence_score', 'N/A')}%")
    print(f"Status:                {flag}")
    print("-" * 78)
    print("Rationale:")
    print(f"  {result.get('rationale', 'N/A')}")
    print(f"\nSupporting quote (verbatim from announcement):")
    print(f'  "{result.get("supporting_quote", "N/A")}"')
    if escalation:
        print(f"\nEscalation reason:")
        print(f"  {result.get('escalation_reason', 'N/A')}")
    print("=" * 78)


def main():
    if API_KEY == "YOUR_KEY_HERE":
        print("⚠️  No API key found. Set the GEMINI_API_KEY environment variable "
              "before running.\n   export GEMINI_API_KEY=\"your_key_here\"")
        return

    # ---------------- Case 1: legacy account, clear standing instructions ----------------
    announcement_1 = (
        "NOTICE OF VOLUNTARY TENDER OFFER — Ridgeline Materials Corp (CUSIP 76582A10). "
        "Ridgeline Materials Corp is offering to purchase up to 8,000,000 shares of its "
        "common stock at a price of $42.50 per share in cash, representing a 15% premium "
        "to the prior closing price. The offer expires at 5:00 PM Eastern Time on "
        "November 14, 2026. Shareholders may tender all, some, or none of their shares. "
        "Partial tenders will be accepted on a pro-rata basis if the offer is oversubscribed."
    )
    account_context_1 = (
        "Account: UMB-CUST-004471 (legacy UMB institutional account, active since 2011)\n"
        "Holdings: 50,000 shares of Ridgeline Materials Corp (CUSIP 76582A10)\n"
        "Standing Instructions: 'For voluntary cash tender offers at a premium of 10% or "
        "greater to market price, tender 100% of eligible shares unless client contacts "
        "custody team directly to override.'"
    )
    result_1 = call_copilot(announcement_1, account_context_1)
    result_1 = enforce_heartland_mitigation(
        result_1, is_heartland_converted=False, standing_instructions_missing=False
    )
    display_result("Legacy account — clear standing instructions", result_1)

    # ---------------- Case 2: Heartland-converted account, missing instructions ----------
    announcement_2 = (
        "NOTICE OF RIGHTS OFFERING — Prairie Grain Cooperative Inc (CUSIP 74019B22). "
        "Prairie Grain Cooperative Inc is issuing transferable subscription rights to "
        "holders of record as of October 30, 2026, entitling holders to purchase one new "
        "common share for every four rights held at a subscription price of $18.00 per "
        "share. Rights not exercised by 5:00 PM Eastern Time on December 5, 2026 will "
        "expire worthless. Rights may also be sold on the open market prior to expiration."
    )
    account_context_2 = (
        "Account: HRTLND-CUST-002218 (converted from Heartland Financial USA, October 2025)\n"
        "Holdings: 12,000 shares of Prairie Grain Cooperative Inc (CUSIP 74019B22)\n"
        "Standing Instructions: [NOT FOUND — record not migrated/standardized during "
        "Heartland conversion]"
    )
    result_2 = call_copilot(announcement_2, account_context_2)
    result_2 = enforce_heartland_mitigation(
        result_2, is_heartland_converted=True, standing_instructions_missing=True
    )
    display_result("Heartland-converted account — missing standing instructions", result_2)


if __name__ == "__main__":
    main()
