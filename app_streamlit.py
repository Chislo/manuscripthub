# app_streamlit.py - ManuscriptHub • Journal Finder (duplicate ID fix + robust session state)
# Copyright 2026 Chisom Ubabukoh
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import streamlit as st
import json
import os
import ollama
import google.generativeai as genai
import pandas as pd
import time
import datetime

st.set_page_config(page_title="ManuscriptHub • Journal Finder", page_icon="📄", layout="wide")

# Initialize session state for persistent inputs
if "title" not in st.session_state:
    st.session_state.title = ""
if "abstract" not in st.session_state:
    st.session_state.abstract = ""
if "recommendations" not in st.session_state:
    st.session_state.recommendations = None
if "result_limit" not in st.session_state:
    st.session_state.result_limit = 10

# Initialize slider defaults in session state if they don't exist
if "w_fit_slider" not in st.session_state: st.session_state.w_fit_slider = 0.4
if "w_prestige_slider" not in st.session_state: st.session_state.w_prestige_slider = 0.3
if "w_speed_slider" not in st.session_state: st.session_state.w_speed_slider = 0.2
if "w_accept_slider" not in st.session_state: st.session_state.w_accept_slider = 0.1

# Rate Limit State
if "last_request_time" not in st.session_state:
    st.session_state.last_request_time = 0
if "request_count" not in st.session_state:
    st.session_state.request_count = 0
if "window_start_time" not in st.session_state:
    st.session_state.window_start_time = time.time()

# ────────────────────────────────────────────────
# Sidebar Logic: Sync Presets & Sliders
# ────────────────────────────────────────────────
def on_preset_change():
    p = st.session_state.preset_radio
    if p == "Balanced":
        st.session_state.w_fit_slider = 0.4
        st.session_state.w_prestige_slider = 0.3
        st.session_state.w_speed_slider = 0.2
        st.session_state.w_accept_slider = 0.1
    elif p == "Max Prestige":
        st.session_state.w_fit_slider = 0.2
        st.session_state.w_prestige_slider = 0.6
        st.session_state.w_speed_slider = 0.1
        st.session_state.w_accept_slider = 0.1
    elif p == "Fastest Review":
        st.session_state.w_fit_slider = 0.2
        st.session_state.w_prestige_slider = 0.1
        st.session_state.w_speed_slider = 0.6
        st.session_state.w_accept_slider = 0.1
    elif p == "Minimize Cost":
        st.session_state.w_fit_slider = 0.3
        st.session_state.w_prestige_slider = 0.1
        st.session_state.w_speed_slider = 0.1
        st.session_state.w_accept_slider = 0.5
    elif p == "Best Fit Only":
        st.session_state.w_fit_slider = 1.0
        st.session_state.w_prestige_slider = 0.0
        st.session_state.w_speed_slider = 0.0
        st.session_state.w_accept_slider = 0.0

def on_slider_change():
    # If any slider is moved, we are no longer in a 'clean' preset
    st.session_state.preset_radio = "Manual"

# ────────────────────────────────────────────────
# Navigation & Page State
# ────────────────────────────────────────────────
if "current_page" not in st.session_state:
    st.session_state.current_page = "Journal Finder"

col_nav1, col_nav2, col_nav3, col_nav4, col_nav5 = st.columns([1.5, 2.5, 1, 1, 1])
with col_nav1:
    if st.button("🔍 Journal Finder", use_container_width=True, type="primary" if st.session_state.current_page == "Journal Finder" else "secondary"):
        st.session_state.current_page = "Journal Finder"
        st.rerun()
with col_nav2:
    if st.button("📄 Manuscript Checker (Soon)", use_container_width=True, type="primary" if st.session_state.current_page == "Manuscript Checker" else "secondary"):
        st.session_state.current_page = "Manuscript Checker"
        st.rerun()
with col_nav3:
    if st.button("📊 Stats", use_container_width=True, type="primary" if st.session_state.current_page == "Analytics" else "secondary"):
        st.session_state.current_page = "Analytics"
        st.rerun()
with col_nav4:
    st.markdown('<a href="#about-section" style="text-decoration:none; color:#444; line-height:3;">About</a>', unsafe_allow_html=True)
with col_nav5:
    st.markdown('<a href="#donate-section" style="text-decoration:none; color:#444; line-height:3;">Donate</a>', unsafe_allow_html=True)

# ────────────────────────────────────────────────
# Logo & Title
# ────────────────────────────────────────────────
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    st.image("logo.png", width=600)

st.markdown("**Find the best journals for your paper — based on fit, prestige, speed, and cost.**")

# ────────────────────────────────────────────────
# Load journal metadata
# ────────────────────────────────────────────────
try:
    with open("journal_metadata.json", "r", encoding="utf-8") as f:
        JOURNAL_METADATA = json.load(f)
except FileNotFoundError:
    st.error("journal_metadata.json not found.")
    st.stop()

# Global journal list generation removed in favor of dynamic filtering"

if st.session_state.current_page == "Journal Finder":
    st.sidebar.header("📌 Hard Filters")
    require_scopus = st.sidebar.checkbox("Scopus indexed only", value=False, key="scopus_filter")
    target_quartiles = st.sidebar.multiselect(
        "Target Quartiles",
        ["Q1", "Q2", "Q3", "Q4"],
        default=["Q1", "Q2"],
        help="Select which journal quality tiers to include (based on SJR)."
    )
    
    # Combined Cost Filter
    cost_filter_choice = st.sidebar.selectbox(
        "Cost Preference",
        ["Any Cost (Show All)", "Free to Publish (No APC)", "No Submission Fee", "Diamond OA (Fully Free)"],
        index=0
    )
    
    # Map UI choices to internal flags
    require_no_submission = (cost_filter_choice == "No Submission Fee" or cost_filter_choice == "Diamond OA (Fully Free)")
    require_free_publish = (cost_filter_choice == "Free to Publish (No APC)" or cost_filter_choice == "Diamond OA (Fully Free)")
    require_diamond_oa = (cost_filter_choice == "Diamond OA (Fully Free)")
    
    if st.sidebar.button("🗑️ Clear Inputs", use_container_width=True):
        st.session_state.title = ""
        st.session_state.abstract = ""
        st.rerun()

    st.sidebar.header("📚 Field")
    fields = [
        "Select for me", 
        "Business/Management", 
        "Economics", 
        "Finance", 
        "Law", 
        "Medicine & Health", 
        "STEM (Science/Tech)", 
        "Social Sciences", 
        "Arts & Humanities", 
        "Psychology", 
        "Other"
    ]
    field_choice = st.sidebar.selectbox("Select broad field", fields, index=0, key="field_select")
    
    st.sidebar.header("🎯 Priorities")
    preset = st.sidebar.radio(
        "Quick preset",
        ["Balanced", "Max Prestige", "Fastest Review", "Minimize Cost", "Best Fit Only", "Manual"],
        index=0,
        key="preset_radio",
        on_change=on_preset_change
    )
    
    # Manual sliders
    w_fit       = st.sidebar.slider("Content & scope fit",       0.0, 1.0, key="w_fit_slider",      on_change=on_slider_change)
    w_prestige  = st.sidebar.slider("Journal prestige",          0.0, 1.0, key="w_prestige_slider",   on_change=on_slider_change)
    w_speed     = st.sidebar.slider("Review/publication speed",  0.0, 1.0, key="w_speed_slider",    on_change=on_slider_change)
    w_accept    = st.sidebar.slider("Acceptance probability",    0.0, 1.0, key="w_accept_slider",   on_change=on_slider_change)
    
    total_w = w_fit + w_prestige + w_speed + w_accept
    if total_w == 0:
        weights = {"fit": 1.0, "prestige": 0.0, "speed": 0.0, "accept": 0.0}
    else:
        weights = {
            "fit": w_fit / total_w,
            "prestige": w_prestige / total_w,
            "speed": w_speed / total_w,
            "accept": w_accept / total_w,
        }
else:
    st.sidebar.info("The Manuscript Checker is coming soon! Sign up on the main page to be notified.")
    # Default values for Manuscript Checker page to avoid name errors
    require_scopus = False
    target_quartiles = []
    require_no_submission = False
    require_free_publish = False
    require_diamond_oa = False
    weights = {"fit": 0.4, "prestige": 0.3, "speed": 0.2, "accept": 0.1}
    field_choice = "Other"


# ────────────────────────────────────────────────
# LLM Helper + JSON validator with retry
# ────────────────────────────────────────────────
def call_llm(prompt, temperature=0.15):
    # 1. Try Google Gemini (Cloud)
    try:
        if "GEMINI_API_KEY" in st.secrets:
            genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
            model = genai.GenerativeModel("gemini-flash-latest")
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature
                )
            )
            return response.text.strip()
    except (FileNotFoundError, KeyError, Exception):
        # Fallback if secrets are missing or Gemini fails
        pass

    # 2. Fallback to Ollama (Local/Remote)
    try:
        # Check if using remote Ollama host via secrets
        remote_host = None
        try:
            remote_host = st.secrets.get("OLLAMA_HOST")
        except:
            pass
            
        if remote_host:
             client = ollama.Client(host=st.secrets["OLLAMA_HOST"])
             response = client.chat(
                model="gpt-oss:120b-cloud", # Assuming user kept this name or change to 'llama3'
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": temperature}
            )
             return response['message']['content'].strip()
        
        # Local Ollama
        response = ollama.chat(
            model="gpt-oss:120b-cloud",
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": temperature}
        )
        return response['message']['content'].strip()
    except Exception as e:
        st.error(f"LLM call failed (Ollama): {str(e)}")
        return None

def parse_llm_json(raw, max_retries=2):
    for attempt in range(max_retries + 1):
        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            json_str = raw[start:end] if start >= 0 and end > start else raw
            return json.loads(json_str)
        except json.JSONDecodeError:
            if attempt == max_retries:
                st.error("Could not parse JSON after retries. Raw:\n" + raw)
                return None
            fix_prompt = f"""Fix this invalid JSON. Return ONLY valid JSON array.

Original:
{raw}

Correct example:
[
  {{"journal": "Name", "rank": 1, "reason": "...", "fit_score": 0.92, "prestige_score": 0.85, "speed_score": 0.65, "acceptance_score": 0.45, "field": "Economics"}}
]
"""
            raw = call_llm(fix_prompt, temperature=0.0)

    return None

def infer_field(title, abstract, fields):
    prompt = f"From these fields: {', '.join(fields[1:])}, infer the best one for this paper. Return only the field name.\n\nTitle: {title}\nAbstract: {abstract}"
    result = call_llm(prompt, temperature=0.1)
    return result if result in fields[1:] else "Other"

# ────────────────────────────────────────────────
# Analytics & Logging
# ────────────────────────────────────────────────
ANALYTICS_FILE = "analytics.csv"

def log_event(event_type, details=""):
    """Logs an event to a persistent CSV file."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Clean details to avoid CSV issues
    details = str(details).replace(",", ";").replace("\n", " ")
    
    file_exists = os.path.isfile(ANALYTICS_FILE)
    try:
        with open(ANALYTICS_FILE, "a", encoding="utf-8") as f:
            if not file_exists:
                f.write("timestamp,event_type,details\n")
            f.write(f"{timestamp},{event_type},{details}\n")
    except Exception as e:
        print(f"Logging error: {e}")

# ────────────────────────────────────────────────
# Task Router (future-proof)
# ────────────────────────────────────────────────
def run_task(task, payload):
    if task == "journal_recommendation":
        return recommend_journals(payload)
    if task == "manuscript_check":
        return {"status": "coming_soon", "message": "Manuscript Checker is under development."}
    return {"error": "Unknown task"}

@st.cache_data(show_spinner=False)
def recommend_journals(payload):
    title = payload["title"]
    abstract = payload["abstract"]
    weights = payload["weights"]
    field_choice = payload["field_choice"]
    json_supported_fields = ["Economics", "Law", "Finance", "Business/Management"]

    if field_choice == "Select for me":
        field_choice = infer_field(title, abstract, fields)

    use_json_db = field_choice in json_supported_fields
    
    # 1. Python-side filtering (ONLY for JSON-supported fields)
    top_candidates = []
    if use_json_db:
        candidates = []
        req_scopus = payload.get("require_scopus")
        req_no_sub = payload.get("require_no_submission")
        req_free_pub = payload.get("require_free_publish")
        req_diamond = payload.get("require_diamond_oa")
        req_quartiles = payload.get("target_quartiles", [])

        for name, data in JOURNAL_METADATA.items():
            # Field filter (loose match)
            if field_choice != "Select for me" and field_choice != "Other":
                j_field = data.get("field", "")
                if field_choice.lower() not in j_field.lower():
                    continue

            # Hard filters
            if req_scopus and not data.get("scopus"): continue
            if req_no_sub and data.get("submission_fee"): continue
            
            # Quartile Filter
            if req_quartiles:
                j_q = data.get("quartile", "")
                if j_q not in req_quartiles:
                    continue
            
            # Free to publish = Free to author (no APC, no sub fee usually)
            if req_free_pub and not data.get("free_to_author"): continue
            
            # Diamond OA = OA + No APC
            if req_diamond:
                 if not data.get("open_access"): continue
                 if data.get("apc"): continue

            candidates.append((name, data))

        # 2. Sort by SJR (Prestige) to pick top N for the LLM
        def get_sjr(item):
            val = item[1].get("sjr")
            if isinstance(val, (int, float)):
                return val
            return 0.0

        candidates.sort(key=get_sjr, reverse=True)
        # Top 80 only to save tokens and speed up generation
        top_candidates = candidates[:80]

    # 3. Build dynamic context or AI instruction
    journal_context = ""
    if use_json_db:
        if not top_candidates:
            return []
        for name, data in top_candidates:
            journal_context += f"- **{name}**\n"
            journal_context += f"  Field: {data.get('field', 'N/A')}\n"
            journal_context += f"  Scope: {data.get('scope', 'N/A')[:120]}...\n"
            journal_context += f"  SJR: {data.get('sjr', 'N/A')} | Accept: {data.get('acceptance_rate', 'N/A')}\n"
            journal_context += f"  Avg review: {data.get('avg_review_months', 'N/A')} mo\n\n"
        context_instruction = "Select the top 20 best matching journals from the CANDIDATE LIST below."
    else:
        journal_context = "[NO LOCAL DATABASE FOR THIS FIELD. USE YOUR INTERNAL EXPERT KNOWLEDGE.]"
        context_instruction = "Use your internal knowledge to recommend the top 20 journals globally for this specific topic."

    prompt = f"""You are an expert academic journal recommender.
    
User paper:
Title: {title}
Abstract: {abstract}
Field: {field_choice}

Priority weights:
- Fit: {weights['fit']:.2f}
- Prestige: {weights['prestige']:.2f}
- Speed: {weights['speed']:.2f}
- Acceptance: {weights['accept']:.2f}

Filters:
- Scopus Only: {'Yes' if payload.get('require_scopus') else 'Optional'}
- Free to Publish: {'Yes' if payload.get('require_free_publish') else 'Optional'}
- No Submission Fee: {'Yes' if payload.get('require_no_submission') else 'Optional'}
- Target Quartiles: {', '.join(payload.get('target_quartiles', [])) if payload.get('target_quartiles') else 'Any'}

Information Source:
{journal_context}

Task:
1. {context_instruction}
2. Ensure you respect the user's priority weights and filters in your selection.
3. Calculate scores (0.0-1.0) for each journal.
4. Return ONLY valid JSON.

Format:
[
  {{
    "journal": "Exact Name From List (or Global Name if AI mode)",
    "rank": 1,
    "reason": "Brief explanation",
    "fit_score": 0.8,
    "prestige_score": 0.9,
    "speed_score": 0.5,
    "acceptance_score": 0.5,
    "field": "Field Name",
    "oa_status": "Subscription",
    "sub_fee": "No",
    "url": "official journal homepage URL"
  }}
]
"""

    raw = call_llm(prompt, temperature=0.1)
    if not raw:
        return []

    return parse_llm_json(raw, max_retries=2)

# ────────────────────────────────────────────────
# Fit label
# ────────────────────────────────────────────────
def fit_label(score):
    if score >= 0.7: return "Excellent fit"
    if score >= 0.55: return "Strong fit"
    if score >= 0.4: return "Moderate fit"
    return "Weak fit"

if st.session_state.current_page == "Journal Finder":
    # ────────────────────────────────────────────────
    # Main Input & Generate
    # ────────────────────────────────────────────────
    st.markdown("### Your paper")
    col_t, col_a = st.columns([1, 2])
    with col_t:
        title = st.text_input(
            "**Title**",
            value=st.session_state.get("title", ""),
            placeholder="e.g., Trade Liberalization and Income Inequality",
            key="title_input_unique"
        )
        st.session_state.title = title

    with col_a:
        abstract = st.text_area(
            "**Abstract**",
            value=st.session_state.get("abstract", ""),
            height=180,
            placeholder="Paste the full abstract here…",
            key="abstract_input_unique"
        )
        st.session_state.abstract = abstract

    if st.button("🔍 Find Best Journals", type="primary", use_container_width=True, key="find_journals_btn"):
        current_time = time.time()

        # Rate Limit Logic
        if current_time - st.session_state.last_request_time < 2:
            st.warning("Please wait a moment before searching again.")
        elif st.session_state.request_count >= 10 and current_time - st.session_state.window_start_time < 60:
            st.error("Rate limit exceeded. Please try again in a minute.")
        else:
            # Reset window if > 60s
            if current_time - st.session_state.window_start_time >= 60:
                 st.session_state.request_count = 0
                 st.session_state.window_start_time = current_time

            st.session_state.request_count += 1
            st.session_state.last_request_time = current_time


            if not title.strip() or not abstract.strip():
                st.warning("Please provide both title and abstract.")
            elif len(abstract.strip()) < 50:
                 st.warning("Abstract must be at least 50 characters to get accurate recommendations.")
            else:
                # High-visibility progress indicator
                with st.status("🚀 ManuscriptHub AI is working...", expanded=True) as status:
                    st.write("🔍 Analyzing manuscript content...")
                    st.write("📂 Filtering journal database...")
                    st.write("🤖 Applying AI-weighted ranking...")
                    
                    # Log the search event
                    log_event("SEARCH", f"Title: {title} | Field: {field_choice} | Scopus: {require_scopus} | Quartiles: {target_quartiles}")
                    
                    payload = {
                        "title": title,
                        "abstract": abstract,
                        "weights": weights,
                        "field_choice": field_choice,
                        "require_scopus": require_scopus,
                        "require_no_submission": require_no_submission,
                        "require_free_publish": require_free_publish,
                        "require_diamond_oa": require_diamond_oa,
                        "target_quartiles": target_quartiles,
                    }

                    recommendations = run_task("journal_recommendation", payload)
                    status.update(label="✅ Analysis Complete!", state="complete", expanded=False)


            if recommendations:
                st.session_state.recommendations = recommendations
                st.session_state.result_limit = 10
                st.success(f"Found {len(recommendations)} matching journals")
            else:
                 st.error("No valid recommendations received. Try again or check LLM connection.")

    if st.session_state.recommendations:
        recommendations = st.session_state.recommendations
        
        # Top recommendation banner
        if recommendations:
            top = recommendations[0]
            st.success(
                f"🏆 Recommended journal: **{top['journal']}**\n\n{top['reason']}",
                icon="🏆"
            )

        for idx, item in enumerate(recommendations[:st.session_state.result_limit]):
            journal = item["journal"]
            meta = JOURNAL_METADATA.get(journal, {})
            
            # Use local meta URL if available, else use AI provided URL
            homepage = meta.get("homepage_url") or item.get("url") or "#"
            expander_key = f"expander_{idx}_{journal.replace(' ', '_')}"
            with st.expander(
                f"{item['rank']}. **{journal}**",
                expanded=(item["rank"] <= 3)
            ):
                st.link_button(f"🌐 Visit **{journal}** Website", homepage, use_container_width=True)
                st.info(item["reason"])

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Fit", f"{item.get('fit_score', '–'):.2f}")
                col2.metric("Prestige", f"{item.get('prestige_score', '–'):.2f}")
                col3.metric("Speed", f"{item.get('speed_score', '–'):.2f}")
                col4.metric("Acceptance", f"{item.get('acceptance_score', '–'):.2f}")

                st.markdown(f"**Assessment:** {fit_label(item.get('fit_score', 0.0))}")

                # Details row (Smart data display)
                details = []
                if meta.get('abdc') and meta.get('abdc') != "N/A": details.append(f"ABDC {meta['abdc']}")
                if meta.get('abs') and meta.get('abs') != "N/A": details.append(f"ABS {meta['abs']}")
                if meta.get('sjr'): details.append(f"SJR {meta['sjr']}")
                details.append(f"Field: {item.get('field', 'N/A')}")
                st.markdown(f"**Details:** {' • '.join(details)}")

                # Cost Model badges
                cost_badges = []
                
                # Use local meta or fall back to LLM-provided info
                is_free_to_author = meta.get("free_to_author")
                is_sub_fee = meta.get("submission_fee")
                is_oa = meta.get("open_access")
                is_apc = meta.get("apc")

                # AI Fallback logic if JSON is empty
                if not meta:
                    is_sub_fee = (item.get("sub_fee") == "Yes")
                    is_oa = ("Open Access" in item.get("oa_status", ""))
                    is_free_to_author = (not is_sub_fee and not is_oa) or ("Diamond" in item.get("oa_status", ""))
                    is_apc = is_oa and ("Diamond" not in item.get("oa_status", ""))

                # 1. Free to publish (Zero base cost)
                if is_free_to_author and not is_sub_fee:
                    if is_oa and not is_apc:
                         # Diamond OA
                         cost_badges.append('<span style="background-color:#e6ffe6; color:#006600; padding:4px 8px; border-radius:4px; font-size:14px; margin-right:8px;">💎 <b>Diamond Open Access</b> (Free to publish & read)</span>')
                    else:
                         # Subscription default
                         cost_badges.append('<span style="background-color:#f0f7ff; color:#004085; padding:4px 8px; border-radius:4px; font-size:14px; margin-right:8px;">✅ <b>Free to Publish</b> (Subscription Model)</span>')
                
                # 2. Submission Fee (WARNING COLOR)
                if is_sub_fee:
                    cost_badges.append('<span style="background-color:#fff3cd; color:#856404; padding:4px 8px; border-radius:4px; font-size:14px; margin-right:8px;">📄 <b>Submission Fee Required</b></span>')
                    if not is_oa:
                         cost_badges.append('<span style="background-color:#f8f9fa; color:#383d41; padding:4px 8px; border-radius:4px; font-size:14px; margin-right:8px;">📧 Subscription Model</span>')
                
                # 3. Paid Open Access (APC)
                if is_apc:
                     cost_badges.append('<span style="background-color:#fff5f5; color:#721c24; padding:4px 8px; border-radius:4px; font-size:14px; margin-right:8px;">💰 <b>Open Access Available</b> (APC applies)</span>')

                if cost_badges:
                     st.markdown(" ".join(cost_badges), unsafe_allow_html=True)
                else:
                     st.markdown('<span style="background-color:#f8f9fa; color:#383d41; padding:4px 8px; border-radius:4px; font-size:14px;">Commonly Subscription/Hybrid</span>', unsafe_allow_html=True)

        if len(recommendations) > st.session_state.result_limit:
            if st.button("Show More", key="show_more_recs"):
                st.session_state.result_limit += 10
                st.rerun()

    if not st.session_state.recommendations:
        st.info("Enter title and abstract to get recommendations.")

    # Readiness button
    st.markdown("---")
    col_btn1, col_btn2 = st.columns([3, 1])
    with col_btn1:
        st.markdown("Want to check if your manuscript is ready for submission?")
    with col_btn2:
        if st.button("Check Readiness →", type="secondary", use_container_width=True):
            st.session_state.current_page = "Manuscript Checker"
            st.rerun()
elif st.session_state.current_page == "Manuscript Checker":
    # ────────────────────────────────────────────────
    # Coming Soon Page (Manuscript Checker)
    # ────────────────────────────────────────────────
    st.markdown("<h1 style='text-align: center; color: #1e40af;'>Manuscript Checker</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align: center; color: #4b5563;'>Coming Soon – Know Before You Submit</h3>", unsafe_allow_html=True)
    
    st.info("Instead of just finding a journal, soon you'll be able to **verify** if your paper meets all requirements.")
    
    col_soon1, col_soon2 = st.columns(2)
    with col_soon1:
        st.markdown("""
        ### Features:
        - **Readiness Score**: 0-100% match against journal guidelines.
        - **Exact Changes**: "Shorten abstract", "Add JEL codes", "Format references".
        - **Guideline Checklist**: Automated check for ethics, formatting, and figures.
        """)
    with col_soon2:
        st.success("🚀 Powered by advanced LLM agents that parse guidelines directly from journal websites.")

    st.divider()
    
    st.markdown("### 📧 Get Early Access")
    with st.form("signup_form"):
        email = st.text_input("Enter your email to be notified when we launch:", placeholder="chom@example.com")
        submit = st.form_submit_button("Notify Me!")
        if submit:
            if email and "@" in email:
                log_event("SIGNUP", email)
                with open("coming_soon_signups.txt", "a") as f:
                    f.write(f"{datetime.datetime.now()} | {email}\n")
                st.success("🎉 Thank you! You've been added to the early access list.")
            else:
                st.error("Please enter a valid email address.")

elif st.session_state.current_page == "Analytics":
    # ────────────────────────────────────────────────
    # Analytics Dashboard
    # ────────────────────────────────────────────────
    st.markdown("<h1 style='text-align: center; color: #1e40af;'>Application Insights 📊</h1>", unsafe_allow_html=True)
    
    # Simple Access Protection
    if "admin_authenticated" not in st.session_state:
        st.session_state.admin_authenticated = False
    
    if not st.session_state.admin_authenticated:
        st.markdown("### 🔐 Admin Access")
        pw = st.text_input("Enter Admin Passcode to view stats:", type="password")
        if pw == "admin123": # Default passcode
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            if pw: st.error("Incorrect passcode.")
            st.stop()

    if not os.path.exists(ANALYTICS_FILE):
        st.info("No analytics data available yet. Start using the app to generate stats!")
    else:
        try:
            df = pd.read_csv(ANALYTICS_FILE)
            
            # Overview Metrics
            total_searches = len(df[df['event_type'] == 'SEARCH'])
            total_signups = len(df[df['event_type'] == 'SIGNUP'])
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Searches", total_searches)
            m2.metric("Newsletter Signups", total_signups)
            m3.metric("Total Events", len(df))
            
            st.divider()
            
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                st.subheader("📈 Usage Trend")
                df['date'] = pd.to_datetime(df['timestamp']).dt.date
                date_counts = df.groupby('date').size().reset_index(name='Events')
                st.bar_chart(date_counts.set_index('date'))
            
            with col_chart2:
                st.subheader("📚 Top Research Fields")
                search_details = df[df['event_type'] == 'SEARCH']['details'].tolist()
                fields_found = []
                for d in search_details:
                    if "Field: " in d:
                        try:
                            f_part = d.split("Field: ")[1].split(" |")[0]
                            fields_found.append(f_part)
                        except: pass
                
                if fields_found:
                    field_counts = pd.Series(fields_found).value_counts()
                    st.bar_chart(field_counts)
                else:
                    st.write("No field data yet.")
            
            # Recent Activity Dataframe
            st.subheader("📋 Recent Activity")
            st.dataframe(df.sort_values(by='timestamp', ascending=False).head(50), use_container_width=True)
            
            if st.button("🗑️ Reset Analytics Data"):
                if os.path.exists(ANALYTICS_FILE):
                    os.remove(ANALYTICS_FILE)
                    st.success("Analytics file deleted. Refreshing...")
                    time.sleep(1)
                    st.rerun()
                    
        except Exception as e:
            st.error(f"Error loading analytics: {e}")
    
    st.stop()

# ────────────────────────────────────────────────
# About & Donate sections
# ────────────────────────────────────────────────
st.markdown("<div id='about-section'></div>", unsafe_allow_html=True)
st.markdown("## About ManuscriptHub")
st.markdown("""
ManuscriptHub is an AI-powered tool designed to help researchers navigate the complex world of academic publishing.  
It uses advanced LLMs to deliver personalized journal recommendations based on your paper's content, priorities, and filters.  

Whether you're optimizing for topical fit, journal prestige, review speed, or cost (APC, submission fees, open access), ManuscriptHub simplifies the process to save time and avoid desk rejections.

### What's Coming Soon: Manuscript Checker
Soon, you'll be able to upload your manuscript (PDF, Word, or text) and get an instant readiness assessment against any journal's guidelines. It will highlight:
- **Compliance checklist** — formatting, word limits, references, ethics, data availability, figures, cover letter
- **Actionable fixes** — "Shorten abstract to 200 words", "Add JEL codes", "Move Table 3 to supplementary material"
- **Readiness score** — 0–100% per journal, with a clear path to 100%

This will make submissions faster, more confident, and less stressful.

### Future: Browser Extension for Submission Workflow
Looking ahead, we're developing a **browser extension** to streamline the entire submission process. It will integrate directly with journal websites to:
- Auto-fill forms and metadata
- Track deadlines and status
- Guide you through peer review and revisions

Stay tuned — early access will be announced soon!

ManuscriptHub is built for the academic community and kept free through donations.  
If it's helped you, consider supporting its continued development.
""")

st.markdown("<div id='donate-section'></div>", unsafe_allow_html=True)
st.markdown("## ❤️ Support ManuscriptHub")
st.markdown(
    """
    <div style="text-align: center; margin: 40px 0;">
        <a href="https://paypal.me/ChisomUbabukoh" target="_blank">
            <img src="https://www.paypalobjects.com/webstatic/mktg/logo/pp_cc_mark_111x69.jpg" 
                 width="110" style="border-radius: 5px;">
            <div style="font-size: 22px; font-weight: bold; color: #003087; margin-top: 12px;">
                Donate Now
            </div>
        </a>
    </div>
    """,
    unsafe_allow_html=True
)

st.caption("Every contribution helps keep ManuscriptHub free forever, independent, and growing. Thank you! 🙏")

st.caption("© 2026 Chisom Ubabukoh • Built for the academic community • [chylouba@gmail.com](mailto:chylouba@gmail.com)")