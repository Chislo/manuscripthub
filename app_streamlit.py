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
import io
import ollama
import google.generativeai as genai
import pandas as pd
import time
import datetime
import re
import pdfplumber
from docx import Document as DocxDocument
from fpdf import FPDF
import requests
from bs4 import BeautifulSoup
from journal_scraper import find_guidelines_url, extract_requirements_from_text

# ────────────────────────────────────────────────
# SEO & App Configuration (MUST be first Streamlit command)
# ────────────────────────────────────────────────
st.set_page_config(
    page_title="ManuscriptHub • Free Journal Finder & Manuscript Checker",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://github.com/Chislo/manuscripthub/issues',
        'About': "ManuscriptHub is a free AI-powered tool to help researchers find the best academic journals, check submission fees, and analyze manuscripts."
    }
)

def inject_seo():
    """Injects real SEO meta tags into the header using Javascript."""
    # We use a script to inject the meta tag specifically for verification
    # Note: Streamlit Cloud often blocks verification bots, so this is a "best effort"
    st.markdown(
        """
        <script>
            // remove existing if present to avoid dupes
            var existing = document.querySelector('meta[name="google-site-verification"]');
            if (existing) existing.remove();

            var meta = document.createElement('meta');
            meta.name = "google-site-verification";
            meta.content = "-rkPJOimCPb2hek8cWMI8IPBkj4hlTGa529vkUbO-i8";
            document.getElementsByTagName('head')[0].appendChild(meta);
            
            // Add other SEO tags
            var metaDesc = document.createElement('meta');
            metaDesc.name = "description";
            metaDesc.content = "Free AI Journal Finder and Manuscript Checker. Find journals with no submission fees.";
            document.getElementsByTagName('head')[0].appendChild(metaDesc);
        </script>
        """,
        unsafe_allow_html=True
    )

inject_seo()

# ────────────────────────────────────────────────
# Document Extraction Helpers
# ────────────────────────────────────────────────
def extract_text_from_pdf(uploaded_file):
    """Extract full text from an uploaded PDF file."""
    text = ""
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        st.error(f"Error reading PDF: {e}")
    return text.strip()

def extract_text_from_docx(uploaded_file):
    """Extract full text from an uploaded Word document."""
    text = ""
    try:
        doc = DocxDocument(uploaded_file)
        for para in doc.paragraphs:
            text += para.text + "\n"
    except Exception as e:
        st.error(f"Error reading Word document: {e}")
    return text.strip()

def analyze_manuscript_text(full_text):
    """Analyze extracted text to detect structure, word count, sections, etc."""
    lines = full_text.split("\n")
    word_count = len(full_text.split())
    
    # Detect common academic sections
    section_patterns = {
        "Introduction": r"(?i)^\s*\d*\.?\s*introduction",
        "Literature Review": r"(?i)^\s*\d*\.?\s*(literature\s+review|related\s+(work|literature)|background)",
        "Methodology/Data": r"(?i)^\s*\d*\.?\s*(method|data|empirical\s+strategy|research\s+design|model)",
        "Results/Findings": r"(?i)^\s*\d*\.?\s*(results?|findings?|empirical\s+results?)",
        "Discussion": r"(?i)^\s*\d*\.?\s*discussion",
        "Conclusion": r"(?i)^\s*\d*\.?\s*conclusions?",
        "JEL Codes": r"(?i)(jel\s+(codes?|classification))",
        "Data Availability Statement": r"(?i)(data\s+availability|data\s+access)",
        "Ethics Statement": r"(?i)(ethics?\s+(statement|approval|declaration))",
        "Conflict of Interest Statement": r"(?i)(conflict\s+of\s+interest|competing\s+interests?|declaration\s+of\s+interest)",
    }
    
    detected_sections = {}
    for section_name, pattern in section_patterns.items():
        for line in lines:
            if re.search(pattern, line.strip()):
                detected_sections[section_name] = True
                break
        if section_name not in detected_sections:
            detected_sections[section_name] = False
    
    # Extract abstract
    abstract = ""
    abstract_match = re.search(
        r"(?i)(?:^|\n)\s*abstract\s*[:\n](.+?)(?=\n\s*(?:\d+\.?\s*)?(?:introduction|keywords?|jel|\n\s*\n))",
        full_text, re.DOTALL
    )
    if abstract_match:
        abstract = abstract_match.group(1).strip()
    elif len(lines) > 5:
        # Fallback: look for a dense paragraph near the start
        for i, line in enumerate(lines[:30]):
            if len(line.split()) > 40:
                abstract = line.strip()
                break
    
    # Detect keywords
    keywords = ""
    kw_match = re.search(r"(?i)keywords?\s*[:\-]\s*(.+?)(?:\n|$)", full_text)
    if kw_match:
        keywords = kw_match.group(1).strip()
    
    # Detect Citation Style
    # Author-Date: (Author, 2023)
    author_date_count = len(re.findall(r"\([A-Za-z\s]+,\s*[12][0-9]{3}\)", full_text))
    # Numerical: [1] or [12, 13]
    numerical_count = len(re.findall(r"\[\d+(?:,\s*\d+)*\]", full_text))
    
    detected_citation_style = "Unknown"
    if author_date_count > numerical_count and author_date_count > 5:
        detected_citation_style = "Author-Date (APA/Harvard)"
    elif numerical_count > author_date_count and numerical_count > 5:
        detected_citation_style = "Numerical (Vancouver/IEEE)"

    # Count references
    ref_count = 0
    in_refs = False
    for line in lines:
        if re.search(r"(?i)^\s*(?:references?|bibliography)\s*$", line.strip()):
            in_refs = True
            continue
        if in_refs and line.strip() and len(line.strip()) > 20:
            ref_count += 1
    # Fallback: count citation-like patterns
    if ref_count == 0:
        ref_count = max(author_date_count, numerical_count)
    
    return {
        "word_count": word_count,
        "abstract": abstract[:2000],  # Cap abstract length
        "keywords": keywords,
        "ref_count": ref_count,
        "detected_sections": detected_sections,
        "citation_style": detected_citation_style,
        "text_preview": full_text[:5000],  # First 5000 chars for LLM context
    }

# ────────────────────────────────────────────────
# LLM & API Configuration
# ────────────────────────────────────────────────

if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

def call_llm(prompt, temperature=0.7):
    """
    Calls the configured LLM (Gemini or Ollama).
    """
    model_choice = "Gemini Pro"
    
    # Fallback to Ollama if no API key
    if "GEMINI_API_KEY" not in st.secrets:
         model_choice = "Ollama (Llama3)"
    
    if model_choice == "Gemini Pro":
        try:
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature
                )
            )
            return response.text
        except Exception as e:
            return f"Error calling Gemini: {e}"
    else:
        # Ollama fallback
        try:
            response = ollama.chat(model='llama3', messages=[
              {'role': 'user', 'content': prompt},
            ])
            return response['message']['content']
        except Exception as e:
            return f"Error calling Ollama: {e}"

# ────────────────────────────────────────────────
# Journal Metadata Load
# ────────────────────────────────────────────────
@st.cache_data
def load_journal_metadata():
    if os.path.exists("journal_metadata.json"):
        with open("journal_metadata.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

JOURNAL_METADATA = load_journal_metadata()

# ────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────

def fit_label(score):
    if score >= 0.8: return "Excellent fit"
    if score >= 0.6: return "Good fit"
    if score >= 0.4: return "Moderate fit"
    return "Weak fit"

def find_journal_meta(journal_name):
    """Robustly find journal metadata, handling minor variations (commas, 'and' vs '&', case)."""
    if not journal_name:
        return {}
        
    # 1. Direct match
    if journal_name in JOURNAL_METADATA:
        return JOURNAL_METADATA[journal_name]
    
    # normalize function
    def normalize(s):
        s = s.lower().replace("&", "and").replace(",", "").replace("-", " ")
        return " ".join(s.split())
    
    target_norm = normalize(journal_name)
    
    # 2. Iterate keys and match normalized
    for key, meta in JOURNAL_METADATA.items():
        if normalize(key) == target_norm:
            return meta
            
    return {}

def format_acceptance_rate(rate, split=False):
    """Convert raw acceptance rate (e.g., 0.08) to human-readable string.
    If split=True, returns (percentage_str, label_str) tuple for use in st.metric."""
    if rate is None or rate == "N/A":
        return ("N/A", "") if split else "N/A"
    try:
        r = float(rate)
        pct = round(r * 100) if r <= 1 else round(r)
        if pct <= 5:
            label = "Highly Selective"
        elif pct <= 15:
            label = "Very Selective"
        elif pct <= 30:
            label = "Selective"
        elif pct <= 50:
            label = "Moderate"
        else:
            label = "Accessible"
        if split:
            return (f"{pct}%", label)
        return f"{pct}% ({label})"
    except (ValueError, TypeError):
        return (str(rate), "") if split else str(rate)

def format_sjr(sjr, split=False):
    """Convert SJR score to human-readable label."""
    if sjr is None or sjr == "N/A":
        return ("N/A", "") if split else "N/A"
    try:
        s = float(sjr)
        if s >= 10:
            label = "World-Leading"
        elif s >= 5:
            label = "Top Tier"
        elif s >= 2:
            label = "High Impact"
        elif s >= 1:
            label = "Good Impact"
        elif s >= 0.5:
            label = "Moderate"
        else:
            label = "Emerging"
        if split:
            return (f"{s:.2f}", label)
        return f"{s:.2f} ({label})"
    except (ValueError, TypeError):
        return (str(sjr), "") if split else str(sjr)

def format_review_time(months, split=False):
    """Convert review time in months to human-readable label."""
    if months is None or months == "N/A":
        return ("N/A", "") if split else "N/A"
    try:
        m = float(months)
        if m <= 2:
            label = "Very Fast"
        elif m <= 4:
            label = "Fast"
        elif m <= 6:
            label = "Average"
        elif m <= 9:
            label = "Slow"
        else:
            label = "Very Slow"
        if split:
            return (f"{m:.1f} mo", label)
        return f"{m:.1f} months ({label})"
    except (ValueError, TypeError):
        return (str(months), "") if split else str(months)

def infer_field(title, abstract, fields):
    prompt = f"From these fields: {', '.join(fields[1:])}, infer the best one for this paper. Return only the field name.\n\nTitle: {title}\nAbstract: {abstract}"
    result = call_llm(prompt, temperature=0.1)
    return result if result in fields[1:] else "Other"

# ────────────────────────────────────────────────
# Analytics & Logging
# ────────────────────────────────────────────────
# Use absolute path so analytics survive Streamlit reruns and working directory changes
ANALYTICS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analytics.csv")

def log_event(event_type, details=""):
    """Logs an event to a persistent CSV file and console (stdout)."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Clean details to avoid CSV issues
    details = str(details).replace(",", ";").replace("\n", " ")
    
    # 1. Log to console (Visible in Streamlit Cloud logs, persists across reboots)
    print(f"[ANALYTICS] {timestamp} | {event_type} | {details}", flush=True)
    
    # 2. Log to localized CSV file (Ephemeral on Streamlit Cloud, persists locally)
    file_exists = os.path.isfile(ANALYTICS_FILE)
    try:
        with open(ANALYTICS_FILE, "a", encoding="utf-8") as f:
            if not file_exists:
                f.write("timestamp,event_type,details\n")
            f.write(f"{timestamp},{event_type},{details}\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"Logging error: {e}")

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
# PDF Generation Helper
# ────────────────────────────────────────────────
def generate_pdf_report(recommendations):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Title
    pdf.set_font("Arial", style="B", size=16)
    pdf.cell(0, 10, "ManuscriptHub - Journal Recommendations", ln=True, align="C")
    pdf.ln(5)
    
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 10, f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align="C")
    pdf.ln(10)
    
    for item in recommendations:
        journal = item["journal"]
        meta = find_journal_meta(journal)
        
        # Journal Title
        pdf.set_font("Arial", style="B", size=12)
        pdf.cell(0, 8, f"{item['rank']}. {journal}", ln=True)
        
        # Metrics Line
        pdf.set_font("Arial", size=10)
        fit_txt = fit_label(item['fit_score'])
        sjr_txt = format_sjr(meta.get('sjr'))
        speed_txt = format_review_time(meta.get('avg_review_months'))
        acc_txt = format_acceptance_rate(meta.get('acceptance_rate'))
        
        metrics = f"Fit: {fit_txt}  |  Prestige: {sjr_txt}  |  Speed: {speed_txt}  |  Accept: {acc_txt}"
        pdf.cell(0, 6, metrics, ln=True)
        
        # Reason Analysis
        pdf.multi_cell(0, 6, f"Reason: {item['reason']}")
        
        # Metadata
        field = item.get('field', 'N/A')
        oa = "Open Access" if meta.get("open_access") else "Subscription"
        fee = "Submission Fee: Yes" if meta.get("submission_fee") else "No Submission Fee"
        pdf.cell(0, 6, f"Field: {field}  |  Model: {oa} ({fee})", ln=True)
        
        pdf.ln(5)
        
    return pdf.output(dest='S').encode('latin-1', 'replace')

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
    if st.button("📄 Manuscript Checker", use_container_width=True, type="primary" if st.session_state.current_page == "Manuscript Checker" else "secondary"):
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

st.markdown("""
### Find the perfect home for your research.
**ManuscriptHub is a free AI-powered journal finder.**
Compare fit, prestige (SJR/Quartile), review speed, and submission fees instantly. 
Our tool analyzes your paper to recommend verification-ready journals in Economics, Law, Finance, Business, and Social Sciences.
""")

# ────────────────────────────────────────────────
# Logic: Journal Recommendation Engine
# ────────────────────────────────────────────────
def run_task(task, payload):
    if task == "journal_recommendation":
        return recommend_journals(payload)
    return []

def recommend_journals(payload):
    user_title = payload.get("title", "").lower()
    user_abstract = payload.get("abstract", "").lower()
    weights = payload.get("weights", {})
    field_filter = payload.get("field_choice", "Select for me")
    
    # 1. Candidate Selection
    candidates = []
    
    # Pre-compute query tokens
    query_tokens = set(re.findall(r'\w+', user_title + " " + user_abstract))
    # Remove common stop words (very basic list)
    stop_words = {"the", "and", "of", "in", "to", "a", "is", "for", "with", "on", "that", "by", "this", "an", "are", "from", "as", "at", "be", "or", "study", "paper", "research", "results", "analysis", "data", "using", "based", "model"}
    query_tokens = {t for t in query_tokens if t not in stop_words and len(t) > 3}
    
    for journal, meta in JOURNAL_METADATA.items():
        # Field Filter
        j_field = meta.get("field", "")
        # Fuzzy field matching if specific field selected
        if field_filter != "Select for me" and field_filter != "Other":
            # Just check if any word from filter matches journal field
            filter_tokens = set(field_filter.lower().replace("/", " ").split())
            j_field_tokens = set(j_field.lower().replace("/", " ").split())
            if not filter_tokens.intersection(j_field_tokens):
                 # Allow cross-disciplinary matches (e.g. Finance in Economics)
                 if "economics" in j_field.lower() and "finance" in field_filter.lower(): pass
                 elif "business" in j_field.lower() and "management" in field_filter.lower(): pass
                 else: continue

        # Hard Constraints
        if payload.get("require_scopus") and not meta.get("scopus"): continue
        
        # Cost Constraints
        is_sub_fee = meta.get("submission_fee")
        is_oa = meta.get("open_access")
        is_apc = meta.get("apc")
        is_free_to_author = meta.get("free_to_author")
        
        if payload.get("require_no_submission") and is_sub_fee: continue
        if payload.get("require_free_publish") and not is_free_to_author: continue
        if payload.get("require_diamond_oa") and (not is_oa or is_apc or is_sub_fee): continue
        
        # Quality Filter
        quartile = meta.get("quartile", "Q4") or "Q4"
        if payload.get("target_quartiles") and quartile not in payload.get("target_quartiles"): continue

        # Scoring
        # 1. Fit Score (Keyword interaction)
        scope_text = (meta.get("scope", "") + " " + meta.get("discipline", "") + " " + meta.get("field", "")).lower()
        scope_tokens = set(re.findall(r'\w+', scope_text))
        
        overlap = len(query_tokens.intersection(scope_tokens))
        # Normalize by log of scope length to avoid bias
        fit_score = min(overlap / 5.0, 1.0) # Cap at 1.0 for >5 keyword hits
        
        # 2. Prestige Score (SJR)
        sjr = meta.get("sjr", 0) or 0
        prestige_score = min(sjr / 4.0, 1.0) # Normalize SJR (top journals are >4 usually)
        
        # 3. Speed Score (months)
        months = meta.get("avg_review_months", 12) or 12
        if months == 0: months = 12
        # Faster is better. 1 month = 1.0, 12 months = 0.0
        speed_score = max(0, 1 - (months / 12.0))
        
        # 4. Acceptance Score
        acc = meta.get("acceptance_rate", 0.1) or 0.1
        # Higher acceptance is "better" for this user preference? 
        # Usually yes, if they maximize 'Acceptance'.
        accept_score = acc # 0.0 to 1.0
        
        # Weighted Total
        final_score = (
            fit_score * weights.get("fit", 0.25) +
            prestige_score * weights.get("prestige", 0.25) +
            speed_score * weights.get("speed", 0.25) +
            accept_score * weights.get("accept", 0.25)
        )
        
        candidates.append({
            "journal": journal,
            "rank": 0, # Placeholder
            "fit_score": fit_score,
            "prestige_score": prestige_score,
            "speed_score": speed_score,
            "acceptance_score": accept_score,
            "final_score": final_score,
            "reason": f"Matches keywords in {j_field}. SJR: {sjr}, Review: {months}mo.",
            "oa_status": "Open Access" if is_oa else "Subscription",
            "sub_fee": "Yes" if is_sub_fee else "No",
            "url": meta.get("homepage_url")
        })

    # Sort and rank
    candidates.sort(key=lambda x: x["final_score"], reverse=True)
    
    # Assign ranks
    for i, c in enumerate(candidates):
        c["rank"] = i + 1
        
    return candidates



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
    st.sidebar.info("Use the Manuscript Checker to verify your paper meets journal requirements before submitting.")
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
# Use absolute path so analytics survive Streamlit reruns and working directory changes
ANALYTICS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analytics.csv")

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
            f.flush()
            os.fsync(f.fileno())
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
            journal_context += f"  SJR: {data.get('sjr', 'N/A')} | Accept: {format_acceptance_rate(data.get('acceptance_rate'))}\n"
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

def find_journal_meta(journal_name):
    """Robustly find journal metadata, handling minor variations (commas, 'and' vs '&', case)."""
    if not journal_name:
        return {}
        
    # 1. Direct match
    if journal_name in JOURNAL_METADATA:
        return JOURNAL_METADATA[journal_name]
    
    # normalize function
    def normalize(s):
        s = s.lower().replace("&", "and").replace(",", "").replace("-", " ")
        return " ".join(s.split())
    
    target_norm = normalize(journal_name)
    
    # 2. Iterate keys and match normalized
    for key, meta in JOURNAL_METADATA.items():
        if normalize(key) == target_norm:
            return meta
            
    return {}

def format_acceptance_rate(rate, split=False):
    """Convert raw acceptance rate (e.g., 0.08) to human-readable string.
    If split=True, returns (percentage_str, label_str) tuple for use in st.metric."""
    if rate is None or rate == "N/A":
        return ("N/A", "") if split else "N/A"
    try:
        r = float(rate)
        pct = round(r * 100) if r <= 1 else round(r)
        if pct <= 5:
            label = "Highly Selective"
        elif pct <= 15:
            label = "Very Selective"
        elif pct <= 30:
            label = "Selective"
        elif pct <= 50:
            label = "Moderate"
        else:
            label = "Accessible"
        if split:
            return (f"{pct}%", label)
        return f"{pct}% ({label})"
    except (ValueError, TypeError):
        return (str(rate), "") if split else str(rate)

def format_sjr(sjr, split=False):
    """Convert SJR score to human-readable label."""
    if sjr is None or sjr == "N/A":
        return ("N/A", "") if split else "N/A"
    try:
        s = float(sjr)
        if s >= 10:
            label = "World-Leading"
        elif s >= 5:
            label = "Top Tier"
        elif s >= 2:
            label = "High Impact"
        elif s >= 1:
            label = "Good Impact"
        elif s >= 0.5:
            label = "Moderate"
        else:
            label = "Emerging"
        if split:
            return (f"{s:.2f}", label)
        return f"{s:.2f} ({label})"
    except (ValueError, TypeError):
        return (str(sjr), "") if split else str(sjr)

def format_review_time(months, split=False):
    """Convert review time in months to human-readable label."""
    if months is None or months == "N/A":
        return ("N/A", "") if split else "N/A"
    try:
        m = float(months)
        if m <= 2:
            label = "Very Fast"
        elif m <= 4:
            label = "Fast"
        elif m <= 6:
            label = "Average"
        elif m <= 9:
            label = "Slow"
        else:
            label = "Very Slow"
        if split:
            return (f"{m:.1f} mo", label)
        return f"{m:.1f} months ({label})"
    except (ValueError, TypeError):
        return (str(months), "") if split else str(months)

# ────────────────────────────────────────────────
# PDF Generation Helper
# ────────────────────────────────────────────────
def generate_pdf_report(recommendations):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Title
    pdf.set_font("Helvetica", style="B", size=16)
    pdf.cell(0, 10, "ManuscriptHub - Journal Recommendations", ln=True, align="C")
    pdf.ln(5)
    
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 10, f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align="C")
    pdf.ln(10)
    
    for item in recommendations:
        journal = item["journal"]
        meta = find_journal_meta(journal)
        
        # Journal Title
        pdf.set_font("Helvetica", style="B", size=12)
        pdf.cell(0, 8, f"{item['rank']}. {journal}", ln=True)
        
        # Metrics Line
        pdf.set_font("Helvetica", size=10)
        fit_txt = fit_label(item.get('fit_score', 0))
        sjr_val, sjr_lbl = format_sjr(meta.get('sjr'), split=True)
        speed_val, speed_lbl = format_review_time(meta.get('avg_review_months'), split=True)
        acc_val, acc_lbl = format_acceptance_rate(meta.get('acceptance_rate'), split=True)
        
        metrics = f"Fit: {item.get('fit_score', 0):.0%} ({fit_txt})  |  Prestige: {sjr_val} ({sjr_lbl})  |  Speed: {speed_val} ({speed_lbl})"
        pdf.cell(0, 6, metrics, ln=True)
        
        # Reason Analysis
        pdf.multi_cell(0, 6, f"Reason: {item['reason']}")
        
        # Metadata
        field = item.get('field', 'N/A')
        oa = "Open Access" if meta.get("open_access") else "Subscription"
        fee = "Submission Fee: Yes" if meta.get("submission_fee") else "No Submission Fee"
        pdf.cell(0, 6, f"Field: {field}  |  Model: {oa} ({fee})", ln=True)
        
        pdf.ln(5)
        
    return bytes(pdf.output())

def generate_readiness_pdf(result, journal_name):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Header
    pdf.set_font("Helvetica", style="B", size=18)
    pdf.cell(0, 10, "Manuscript Readiness Report", ln=True, align="C")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 10, f"Generated by ManuscriptHub on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align="C")
    pdf.ln(10)
    
    # Overall Score
    score = result.get("readiness_score", 0)
    pdf.set_font("Helvetica", style="B", size=14)
    pdf.cell(0, 10, f"Overall Readiness Score: {score}/100", ln=True)
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 8, f"Verdict: {result.get('overall_verdict', 'N/A')}")
    pdf.ln(5)
    
    # Details
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, f"Target Journal: {journal_name}", ln=True)
    pdf.ln(5)
    
    # Feedback sections
    for section, title in [("abstract_feedback", "Abstract Analysis"), 
                          ("structure_feedback", "Structure & Formatting"),
                          ("content_feedback", "Content & Rigor")]:
        fb = result.get(section, {})
        pdf.set_font("Helvetica", style="B", size=12)
        pdf.cell(0, 10, f"{title} (Score: {fb.get('score', 'N/A')}/100)", ln=True)
        pdf.set_font("Helvetica", size=10)
        
        if fb.get("issues"):
            pdf.set_font("Helvetica", style="I", size=10)
            pdf.cell(0, 6, "Issues identified:", ln=True)
            pdf.set_font("Helvetica", size=10)
            for issue in fb["issues"]:
                pdf.multi_cell(0, 6, f"- {issue}")
        
        if fb.get("suggestion"):
            pdf.set_font("Helvetica", style="B", size=10)
            pdf.multi_cell(0, 6, f"Recommendation: {fb['suggestion']}")
        pdf.ln(5)
    
    # Action Items
    pdf.set_font("Helvetica", style="B", size=13)
    pdf.cell(0, 10, "Action Items for Submission:", ln=True)
    pdf.set_font("Helvetica", size=10)
    for i, item in enumerate(result.get("action_items", []), 1):
        pdf.multi_cell(0, 6, f"{i}. {item}")
    pdf.ln(10)
    
    # Compliance
    pdf.set_font("Helvetica", style="B", size=13)
    pdf.cell(0, 10, "Compliance Checklist:", ln=True)
    pdf.set_font("Helvetica", size=10)
    for chk in result.get("compliance_checklist", []):
        status = "PASS" if chk.get("status") == "pass" else "WARNING"
        pdf.multi_cell(0, 6, f"[{status}] {chk.get('item')}: {chk.get('note')}")
    pdf.ln(5)

    # footer
    pdf.set_font("Helvetica", size=8)
    pdf.cell(0, 10, "This report is powered by ManuscriptHubAI. Visit manuscripthub.com", ln=True, align="C")
    
    return bytes(pdf.output())

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
        recommendations = None  # Initialize to avoid UnboundLocalError

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
            elif recommendations is not None:  # Empty list (no matches)
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

                # Enhanced Metrics Grid (Matching Manuscript Checker style)
                m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                
                # Fit
                f_val = f"{item.get('fit_score', 0):.0%}"
                f_lbl = fit_label(item.get('fit_score', 0))
                m_col1.metric("Fit", f_val, delta=f_lbl, delta_color="normal")
                
                # Prestige
                p_val, p_lbl = format_sjr(meta.get('sjr'), split=True)
                m_col2.metric("Prestige (SJR)", p_val, delta=p_lbl, delta_color="off")
                
                # Speed
                s_val, s_lbl = format_review_time(meta.get('avg_review_months'), split=True)
                m_col3.metric("Review Speed", s_val, delta=s_lbl, delta_color="off")
                
                # Acceptance
                a_val, a_lbl = format_acceptance_rate(meta.get('acceptance_rate'), split=True)
                m_col4.metric("Acceptance", a_val, delta=a_lbl, delta_color="off")

                # Details row (Smart data display)
                details = []
                if meta.get('abdc') and meta.get('abdc') != "N/A": details.append(f"ABDC {meta['abdc']}")
                if meta.get('abs') and meta.get('abs') != "N/A": details.append(f"ABS {meta['abs']}")
                details.append(f"Field: {item.get('field', 'N/A')}")
                st.markdown(f"**Details:** {' • '.join(details)}")

                # Cost Model badges — clear differentiation
                cost_badges = []
                
                # Use local meta or fall back to LLM-provided info
                is_free_to_author = meta.get("free_to_author")
                is_sub_fee = meta.get("submission_fee")
                is_oa = meta.get("open_access")
                is_apc = meta.get("apc")

                # AI Fallback logic if journal not in our database
                if not meta:
                    is_sub_fee = (item.get("sub_fee") == "Yes")
                    is_oa = ("Open Access" in item.get("oa_status", ""))
                    is_free_to_author = (not is_sub_fee and not is_oa) or ("Diamond" in item.get("oa_status", ""))
                    is_apc = is_oa and ("Diamond" not in item.get("oa_status", ""))

                # ─── Publishing Cost Model ───
                if is_oa and not is_apc:
                    # Diamond OA — completely free
                    cost_badges.append('<span style="background-color:#e6ffe6; color:#006600; padding:4px 10px; border-radius:4px; font-size:14px; margin-right:8px;">💎 <b>Diamond Open Access</b> — Free to publish & read</span>')
                elif is_oa and is_apc:
                    # Gold OA — APC required
                    cost_badges.append('<span style="background-color:#fff0e6; color:#7a4510; padding:4px 10px; border-radius:4px; font-size:14px; margin-right:8px;">🔓 <b>Open Access</b> — APC (Article Processing Charge) applies</span>')
                elif not is_oa:
                    # Subscription model — free to publish
                    cost_badges.append('<span style="background-color:#f0f7ff; color:#004085; padding:4px 10px; border-radius:4px; font-size:14px; margin-right:8px;">✅ <b>Free to Publish</b> — Subscription journal (readers pay, not authors)</span>')
                
                # ─── Submission Fee (separate from APC!) ───
                if is_sub_fee:
                    cost_badges.append('<span style="background-color:#fff3cd; color:#856404; padding:4px 10px; border-radius:4px; font-size:14px; margin-right:8px;">⚠️ <b>Submission Fee</b> — Fee charged when you submit (separate from any APC)</span>')

                if cost_badges:
                    st.markdown(" ".join(cost_badges), unsafe_allow_html=True)


                if st.button(f"📄 Check Readiness → {journal}", key=f"check_readiness_{idx}_{journal.replace(' ', '_')}", use_container_width=True):
                    st.session_state.mc_target_journal = journal
                    st.session_state.current_page = "Manuscript Checker"
                    st.session_state.checker_result = None
                    st.rerun()

        if len(recommendations) > st.session_state.result_limit:
            if st.button("Show More", key="show_more_recs"):
                st.session_state.result_limit += 10
                st.rerun()

        # ── Download Results Button ──────────────────────────
        st.markdown("---")
        st.markdown("### 📥 Export Results")
        col_dl1, col_dl2 = st.columns(2)
        
        if recommendations:
            # Build CSV data
            csv_rows = []
            for item in recommendations:
                journal = item["journal"]
                meta = find_journal_meta(journal)
                homepage = meta.get("homepage_url", meta.get("website", ""))
                
                csv_rows.append({
                    "Rank": item.get("rank", ""),
                    "Journal": journal,
                    "Fit Score": item.get("fit_score", ""),
                    "Prestige Score": item.get("prestige_score", ""),
                    "Speed Score": item.get("speed_score", ""),
                    "Acceptance Score": item.get("acceptance_score", ""),
                    "Assessment": fit_label(item.get("fit_score", 0.0)),
                    "Reason": item.get("reason", ""),
                    "Field": item.get("field", ""),
                    "SJR": meta.get("sjr", item.get("sjr", "")),
                    "Quartile": meta.get("quartile", ""),
                    "ABDC": meta.get("abdc", ""),
                    "ABS": meta.get("abs", ""),
                    "Scopus": "Yes" if meta.get("scopus") else "No" if meta else "",
                    "Open Access": "Yes" if meta.get("open_access") else "No" if meta else item.get("oa_status", ""),
                    "Submission Fee": "Yes" if meta.get("submission_fee") else "No" if meta else item.get("sub_fee", ""),
                    "Homepage": homepage,
                })
            df_export = pd.DataFrame(csv_rows)
            csv_buffer = io.StringIO()
            df_export.to_csv(csv_buffer, index=False)
            csv_data = csv_buffer.getvalue()
            
            with col_dl1:
                st.download_button(
                    label="⬇️ Download as CSV",
                    data=csv_data,
                    file_name=f"manuscripthub_results_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="download_csv_btn"
                )
            
            with col_dl2:
                # PDF Generation
                pdf_data = generate_pdf_report(recommendations)
                st.download_button(
                    label="📄 Download as PDF Report",
                    data=pdf_data,
                    file_name=f"manuscripthub_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="download_pdf_btn"
                )
        
        with col_dl2:
            # Build a human-readable text report
            report_lines = []
            report_lines.append("ManuscriptHub — Journal Recommendations Report")
            report_lines.append(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            report_lines.append(f"Paper Title: {st.session_state.get('title', 'N/A')}")
            report_lines.append("=" * 60)
            report_lines.append("")
            for item in recommendations:
                journal = item["journal"]
                meta = JOURNAL_METADATA.get(journal, {})
                homepage = meta.get("homepage_url") or item.get("url") or "N/A"
                report_lines.append(f"#{item.get('rank', '?')}  {journal}")
                report_lines.append(f"    Fit: {item.get('fit_score', '–')}  |  Prestige: {item.get('prestige_score', '–')}  |  Speed: {item.get('speed_score', '–')}  |  Acceptance: {item.get('acceptance_score', '–')}")
                report_lines.append(f"    Assessment: {fit_label(item.get('fit_score', 0.0))}")
                report_lines.append(f"    Reason: {item.get('reason', '')}")
                if meta.get('sjr'): report_lines.append(f"    SJR: {meta['sjr']} | Quartile: {meta.get('quartile', 'N/A')}")
                if meta.get('abdc'): report_lines.append(f"    ABDC: {meta['abdc']} | ABS: {meta.get('abs', 'N/A')}")
                report_lines.append(f"    Website: {homepage}")
                report_lines.append("")
            report_lines.append("=" * 60)
            report_lines.append("Powered by ManuscriptHub • manuscripthub.com")
            report_text = "\n".join(report_lines)
            
            st.download_button(
                label="📄 Download as Text Report",
                data=report_text,
                file_name=f"manuscripthub_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain",
                use_container_width=True,
                key="download_txt_btn"
            )

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
    # Manuscript Checker — Full Implementation with File Upload
    # ────────────────────────────────────────────────
    st.markdown("<h1 style='text-align: center; color: #1e40af;'>📄 Manuscript Checker</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align: center; color: #4b5563;'>Know Before You Submit — Journal-Specific Readiness Analysis</h3>", unsafe_allow_html=True)
    
    st.markdown("""
    Upload your manuscript (PDF or Word) and select your target journal for a **journal-specific readiness assessment**.
    The checker automatically extracts your paper's structure and evaluates compliance against your target journal's requirements.
    """)
    
    st.divider()
    # ── Manuscript Checker Sidebar ──
    st.sidebar.header("📄 Checker Settings")
    check_depth = st.sidebar.radio(
        "Analysis Depth",
        ["Quick Check", "Standard", "Deep Analysis"],
        index=1,
        key="check_depth_radio",
        help="Quick = structure only. Standard = structure + content. Deep = full compliance review."
    )
    
    st.sidebar.markdown("---")
    do_live_check = st.sidebar.checkbox(
        "🌐 Fetch Live Guidelines",
        value=False,
        key="mc_live_check",
        help="Fetch current 'For Authors' guidelines from the journal website for 100% accuracy on word limits and formatting. (Takes ~10s longer)"
    )
    
    # ── Target Journal Selection ──
    st.markdown("### 🎯 Target Journal")
    
    # Build journal list for selectbox
    all_journal_names = sorted(JOURNAL_METADATA.keys())
    
    # Check if coming from Journal Finder with a pre-selected journal
    prefilled_journal = st.session_state.get("mc_target_journal", "")
    
    # Journal selection: searchable selectbox from database + manual entry
    journal_mode = st.radio(
        "How would you like to select a journal?",
        ["Select from database", "Type journal name manually"],
        index=0 if prefilled_journal in all_journal_names else 1,
        key="journal_mode_radio",
        horizontal=True
    )
    
    if journal_mode == "Select from database":
        # Search filter + selectbox combo
        search_query = st.text_input(
            "🔍 **Search journals**",
            value=prefilled_journal if prefilled_journal else "",
            placeholder="Start typing to filter (e.g., 'Journal of Finance')",
            key="mc_journal_search"
        )
        
        # Filter journal list based on search
        if search_query.strip():
            filtered_journals = [j for j in all_journal_names if search_query.lower() in j.lower()]
        else:
            filtered_journals = all_journal_names
        
        if filtered_journals:
            # Find index of pre-filled journal in filtered list
            default_idx = 0
            if prefilled_journal and prefilled_journal in filtered_journals:
                default_idx = filtered_journals.index(prefilled_journal)
            
            mc_journal = st.selectbox(
                f"**Select from {len(filtered_journals)} matching journals**",
                filtered_journals,
                index=default_idx,
                key="mc_journal_selectbox",
            )
        else:
            st.warning(f"No journals found matching '{search_query}'. Try a different search or switch to manual entry.")
            mc_journal = search_query  # Use the search text as fallback
    else:
        mc_journal = st.text_input(
            "**Target Journal Name**",
            value=prefilled_journal,
            placeholder="e.g., Journal of Financial Economics",
            key="mc_journal_manual_input"
        )
    
    # Show journal metadata preview if available
    if mc_journal and mc_journal in JOURNAL_METADATA:
        jmeta = JOURNAL_METADATA[mc_journal]
        jm_cols = st.columns(5)
        sjr_val, sjr_label = format_sjr(jmeta.get("sjr"), split=True)
        jm_cols[0].metric("SJR", sjr_val, delta=sjr_label, delta_color="off")
        jm_cols[1].metric("Quartile", jmeta.get("quartile", "N/A"))
        acc_pct, acc_label = format_acceptance_rate(jmeta.get('acceptance_rate'), split=True)
        jm_cols[2].metric("Acceptance", acc_pct, delta=acc_label, delta_color="off")
        rev_val, rev_label = format_review_time(jmeta.get('avg_review_months'), split=True)
        jm_cols[3].metric("Avg Review", rev_val, delta=rev_label, delta_color="off")
        jm_cols[4].metric("Field", jmeta.get("field", "N/A"))
        if jmeta.get("scope"):
            st.caption(f"**Scope:** {jmeta['scope'][:200]}...")
        # Link to journal homepage / submission guidelines
        homepage = jmeta.get("homepage_url", jmeta.get("website", ""))
        search_url = f"https://www.google.com/search?q={mc_journal.replace(' ', '+')}+journal+submission"
        
        if homepage:
            st.markdown(f"🔗 [**Visit Journal Website**]({homepage}) &nbsp;|&nbsp; 🔍 [Search Google]({search_url})", unsafe_allow_html=True)
        else:
            st.markdown(f"� [**Search Google for Journal Website**]({search_url})", unsafe_allow_html=True)
    
    st.divider()
    
    # ── File Upload ──
    st.markdown("### � Upload Your Manuscript")
    uploaded_file = st.file_uploader(
        "Upload your manuscript (PDF or Word)",
        type=["pdf", "docx", "doc"],
        key="mc_file_uploader",
        help="Upload your full paper to auto-extract title, abstract, word count, sections, and references."
    )
    
    # Initialize auto-extracted data
    if "mc_extracted" not in st.session_state:
        st.session_state.mc_extracted = None
    
    extracted = st.session_state.mc_extracted
    
    if uploaded_file is not None:
        file_name = uploaded_file.name.lower()
        # Only re-extract if we haven't already processed this file
        already_processed = st.session_state.get("mc_last_file_name") == uploaded_file.name
        if not already_processed:
            with st.spinner("📖 Extracting text from your manuscript..."):
                if file_name.endswith(".pdf"):
                    full_text = extract_text_from_pdf(uploaded_file)
                elif file_name.endswith(".docx") or file_name.endswith(".doc"):
                    full_text = extract_text_from_docx(uploaded_file)
                else:
                    full_text = ""
                    st.error("Unsupported file type.")
                
                if full_text:
                    extracted = analyze_manuscript_text(full_text)
                    st.session_state.mc_extracted = extracted
                    st.session_state.mc_last_file_name = uploaded_file.name
                    
                    # Directly set session state for widgets — this is the CORRECT
                    # Streamlit pattern for auto-populating fields with keys
                    # Title: use first non-empty line from text (before abstract)
                    lines = full_text.strip().split("\n")
                    title_candidate = ""
                    for line in lines[:10]:
                        stripped = line.strip()
                        if stripped and len(stripped) > 5 and len(stripped.split()) <= 25:
                            title_candidate = stripped
                            break
                    st.session_state.mc_title_input = title_candidate
                    st.session_state.mc_abstract_input = extracted.get("abstract", "")
                    st.session_state.mc_wordcount_input = extracted.get("word_count", 0)
                    st.session_state.mc_keywords_input = extracted.get("keywords", "")
                    st.session_state.mc_refcount_input = extracted.get("ref_count", 0)
                    
                    st.success(f"✅ Extracted **{extracted['word_count']:,}** words from **{uploaded_file.name}**")
                    st.rerun()  # Rerun to reflect the new session state values in widgets
                else:
                    st.warning("Could not extract text from the uploaded file. Please enter details manually below.")
        else:
            st.success(f"✅ Document loaded: **{uploaded_file.name}** ({extracted['word_count']:,} words)" if extracted else "")
    
    # ── Show extraction results + manual override ──
    st.markdown("### 📝 Manuscript Details")
    if extracted:
        st.info("ℹ️ Fields below are auto-populated from your uploaded document. You can edit any field manually.")
    
    col_mc1, col_mc2 = st.columns([1, 1])
    with col_mc1:
        mc_title = st.text_input(
            "**Manuscript Title**",
            placeholder="e.g., The Impact of Trade Policy on Income Distribution",
            key="mc_title_input"
        )
        mc_abstract = st.text_area(
            "**Abstract**",
            height=150,
            placeholder="Paste your full abstract here (or upload a file to auto-detect)…",
            key="mc_abstract_input"
        )
        mc_wordcount = st.number_input(
            "**Total Word Count**",
            min_value=0,
            max_value=100000,
            step=500,
            key="mc_wordcount_input"
        )
    
    with col_mc2:
        mc_keywords = st.text_input(
            "**Keywords** (comma-separated)",
            placeholder="e.g., trade policy, inequality, tariffs, developing countries",
            key="mc_keywords_input"
        )
        mc_ref_count = st.number_input(
            "**Number of References**",
            min_value=0,
            max_value=1000,
            step=5,
            key="mc_refcount_input"
        )
        if extracted:
            st.markdown("**📄 Document Preview** (first 500 chars)")
            st.text_area("Preview", value=extracted.get("text_preview", "")[:500], height=100, disabled=True, key="mc_doc_preview")
    
    st.markdown("#### 📋 Manuscript Structure Checklist")
    if extracted:
        st.caption("Auto-detected from your upload — adjust if needed.")
    
    det = extracted.get("detected_sections", {}) if extracted else {}
    col_chk1, col_chk2, col_chk3 = st.columns(3)
    with col_chk1:
        has_intro = st.checkbox("Introduction section", value=det.get("Introduction", True), key="chk_intro")
        has_lit_review = st.checkbox("Literature review", value=det.get("Literature Review", True), key="chk_litrev")
        has_methodology = st.checkbox("Methodology/Data section", value=det.get("Methodology/Data", True), key="chk_method")
    with col_chk2:
        has_results = st.checkbox("Results/Findings", value=det.get("Results/Findings", True), key="chk_results")
        has_discussion = st.checkbox("Discussion", value=det.get("Discussion", True), key="chk_discussion")
        has_conclusion = st.checkbox("Conclusion", value=det.get("Conclusion", True), key="chk_conclusion")
    with col_chk3:
        has_jel = st.checkbox("JEL codes (Economics)", value=det.get("JEL Codes", False), key="chk_jel")
        has_data_avail = st.checkbox("Data availability statement", value=det.get("Data Availability Statement", False), key="chk_data")
        has_ethics = st.checkbox("Ethics statement", value=det.get("Ethics Statement", False), key="chk_ethics")
        has_conflict = st.checkbox("Conflict of interest statement", value=det.get("Conflict of Interest Statement", False), key="chk_conflict")
        has_cover_letter = st.checkbox("Cover letter prepared", value=False, key="chk_cover")
    
    st.divider()
    
    # ── Initialize checker state ──
    if "checker_result" not in st.session_state:
        st.session_state.checker_result = None
    
    if st.button("🔍 Check Manuscript Readiness", type="primary", use_container_width=True, key="check_manuscript_btn"):
        has_abstract = mc_abstract.strip() if mc_abstract else ""
        has_upload = extracted is not None
        
        if not mc_title.strip() and not has_upload:
            st.warning("Please provide a title or upload a manuscript.")
        elif not has_abstract and not has_upload:
            st.warning("Please provide an abstract or upload a manuscript.")
        elif not mc_journal.strip():
            st.warning("Please specify a target journal.")
        else:
            # 1. Gather structure info
            structure_items = {
                "Introduction": has_intro,
                "Literature Review": has_lit_review,
                "Methodology/Data": has_methodology,
                "Results/Findings": has_results,
                "Discussion": has_discussion,
                "Conclusion": has_conclusion,
                "JEL Codes": has_jel,
                "Data Availability Statement": has_data_avail,
                "Ethics Statement": has_ethics,
                "Conflict of Interest Statement": has_conflict,
                "Cover Letter": has_cover_letter,
            }
            present_sections = [k for k, v in structure_items.items() if v]
            missing_sections = [k for k, v in structure_items.items() if not v]
            
            # 2. Build journal context
            journal_meta = JOURNAL_METADATA.get(mc_journal.strip(), {})
            
            # --- LIVE CHECK LOGIC ---
            live_req_text = ""
            if st.session_state.get("mc_live_check"):
                status_placeholder = st.empty()
                with status_placeholder.status(f"🌐 Live Verification: {mc_journal}", expanded=True) as status_box:
                    st.write("🔍 Locating official submission guidelines...")
                    homepage = journal_meta.get("homepage_url", "")
                    g_url = find_guidelines_url(mc_journal.strip(), homepage)
                    
                    if g_url:
                        st.write(f"📥 Reading guidelines from {g_url}...")
                        try:
                            res = requests.get(g_url, timeout=12)
                            if res.status_code == 200:
                                soup = BeautifulSoup(res.text, 'html.parser')
                                # Remove scripts/styles
                                for s in soup(["script", "style"]): s.decompose()
                                clean_text = " ".join(soup.get_text().split())
                                
                                st.write("🤖 Extracting specific requirements (word counts, style)...")
                                live_reqs = extract_requirements_from_text(clean_text, mc_journal)
                                if live_reqs:
                                    live_req_text = f"VERIFIED LIVE REQUIREMENTS FOR {mc_journal}:\n{json.dumps(live_reqs, indent=2)}"
                                    st.session_state.mc_live_verified = True
                                    st.success("✅ Live guidelines successfully incorporated.")
                                else:
                                    st.session_state.mc_live_verified = False
                                    st.warning("⚠️ guidelines found but could not extract structured data.")
                            else:
                                st.session_state.mc_live_verified = False
                                st.warning(f"⚠️ Could not access guidelines page (Status {res.status_code}).")
                        except Exception as e:
                            st.session_state.mc_live_verified = False
                            st.warning(f"⚠️ Error fetching live data: {str(e)}")
                    else:
                        st.session_state.mc_live_verified = False
                        st.warning("⚠️ Could not find a direct guidelines link.")
                    status_box.update(label="Verification Complete", state="complete", expanded=False)
            else:
                st.session_state.mc_live_verified = False
            # --- END LIVE CHECK LOGIC ---

            journal_context = ""
            if journal_meta:
                journal_context = f"""
KNOWN JOURNAL METADATA FOR {mc_journal.upper()}:
- Publisher: {journal_meta.get('publisher', 'N/A')}
- Field: {journal_meta.get('field', 'N/A')}
- Scope: {journal_meta.get('scope', 'N/A')}
- SJR: {journal_meta.get('sjr', 'N/A')} | Quartile: {journal_meta.get('quartile', 'N/A')}
- Acceptance Rate: {format_acceptance_rate(journal_meta.get('acceptance_rate'))}
- Avg Review: {journal_meta.get('avg_review_months', 'N/A')} months
"""
            
            if live_req_text:
                journal_context += f"\n{live_req_text}\n"
                journal_context += "\nNOTE: The LIVE REQUIREMENTS above are from the journal's official website. PRIORITIZE THEM over internal knowledge."
            else:
                journal_context += f"\n[NO LIVE DATA FOUND. Use your expert knowledge of {mc_journal} guidelines.]"

            # 3. Build manuscript content context from upload
            manuscript_content = ""
            if extracted:
                manuscript_content = f"""
UPLOADED MANUSCRIPT CONTENT (excerpt, {extracted['word_count']} total words):
---
{extracted.get('text_preview', '')}
---
"""
            
            depth_instruction = {
                "Quick Check": "Provide a brief structural assessment only. Focus on missing sections and formatting basics.",
                "Standard": "Provide a thorough assessment covering structure, content quality, and compliance.",
                "Deep Analysis": "Provide an exhaustive, publication-quality assessment. Analyze structure, content depth, methodological rigor, citation practices, and full compliance."
            }

            
            checker_prompt = f"""You are an expert academic manuscript reviewer and journal submission advisor specializing in {mc_journal}.

Manuscript Information:
- Title: {mc_title if mc_title.strip() else 'Not provided'}
- Abstract: {mc_abstract if mc_abstract.strip() else 'See uploaded content below'}
- Target Journal: {mc_journal}
- Word Count: {mc_wordcount if mc_wordcount > 0 else 'Not specified'}
- Keywords: {mc_keywords if mc_keywords.strip() else 'Not specified'}
- Number of References: {mc_ref_count if mc_ref_count > 0 else 'Not specified'}
- Detected Citation Style: {extracted.get('citation_style', 'Unknown') if extracted else 'Unknown'}
- Sections Present: {', '.join(present_sections) if present_sections else 'None specified'}
- Sections Missing: {', '.join(missing_sections) if missing_sections else 'None – all checked'}
- Document Uploaded: {'Yes' if extracted else 'No (manual input only)'}
- Analysis Depth: {check_depth}

{journal_context}

{manuscript_content}

Analysis Depth: {check_depth}
{depth_instruction[check_depth]}

IMPORTANT INSTRUCTIONS:
1. Your analysis must be SPECIFIC TO {mc_journal}. Reference this journal by name in your feedback.
2. If journal metadata is provided above, use it to check compliance (e.g., word limits typical for this journal's quartile/field, required sections for this discipline, whether JEL codes are needed, etc.).
3. If a full manuscript was uploaded, analyze the actual content — not just the metadata.
4. Evaluate how ready this manuscript is for submission to {mc_journal}.
5. Provide a readiness score from 0-100.
6. Provide specific, actionable feedback with journal-specific recommendations.

Return your analysis as valid JSON in this exact format:
{{
  "readiness_score": 75,
  "overall_verdict": "Good but needs revisions before submitting to {mc_journal}",
  "abstract_feedback": {{
    "score": 80,
    "issues": ["Abstract could be more concise for {mc_journal}", "Missing key contribution statement"],
    "suggestion": "Reduce to 250 words and emphasize the novel contribution in the first two sentences."
  }},
  "structure_feedback": {{
    "score": 70,
    "missing_critical": ["Data Availability Statement"],
    "missing_recommended": ["JEL Codes"],
    "suggestion": "Add a data availability statement as {mc_journal} requires this."
  }},
  "content_feedback": {{
    "score": 75,
    "strengths": ["Clear research question", "Timely topic"],
    "weaknesses": ["Abstract lacks methodological detail"],
    "suggestion": "Briefly mention the econometric approach in the abstract to meet {mc_journal} standards."
  }},
  "compliance_checklist": [
    {{
      "item": "Word count within {mc_journal} limits",
      "status": "pass",
      "note": "Typical limit for this journal is 8000-12000 words"
    }},
    {{
      "item": "Ethics statement",
      "status": "warning",
      "note": "Not provided, required by {mc_journal}"
    }}
  ],
  "action_items": [
    "Shorten abstract to under 250 words (required by {mc_journal})",
    "Add JEL classification codes",
    "Include data availability statement",
    "Prepare a cover letter addressing the editor of {mc_journal}"
  ],
  "journal_fit_assessment": "This manuscript appears to be a reasonable fit for {mc_journal}'s scope, but the methodology section should be strengthened to match the journal's empirical rigor expectations."
}}
"""
            
            with st.status("🔍 Analyzing manuscript readiness...", expanded=True) as status:
                st.write("📋 Checking manuscript structure...")
                st.write(f"📚 Evaluating fit for {mc_journal}...")
                st.write("✍️ Generating actionable feedback...")
                
                log_event("MANUSCRIPT_CHECK", f"Title: {mc_title} | Journal: {mc_journal} | Depth: {check_depth}")
                
                raw_result = call_llm(checker_prompt, temperature=0.15)
                status.update(label="✅ Analysis Complete!", state="complete", expanded=False)
            
            if raw_result:
                try:
                    # Parse JSON from LLM response
                    json_match = re.search(r'\{[\s\S]*\}', raw_result)
                    if json_match:
                        checker_data = json.loads(json_match.group())
                        st.session_state.checker_result = checker_data
                    else:
                        st.error("Could not parse the analysis result. Please try again.")
                except json.JSONDecodeError:
                    st.error("AI returned invalid format. Please try again.")
            else:
                st.error("Analysis failed — check your LLM connection.")
    
    # ── Display Results ──
    if st.session_state.checker_result:
        result = st.session_state.checker_result
        
        # Readiness Score Banner
        score = result.get("readiness_score", 0)
        if score >= 80:
            score_color = "#16a34a"  # green
            score_emoji = "🟢"
            score_bg = "#f0fdf4"
        elif score >= 60:
            score_color = "#ca8a04"  # amber
            score_emoji = "🟡"
            score_bg = "#fefce8"
        else:
            score_color = "#dc2626"  # red
            score_emoji = "🔴"
            score_bg = "#fef2f2"
        
        st.markdown(f"""
        <div style="background: {score_bg}; border: 2px solid {score_color}; border-radius: 12px; padding: 24px; text-align: center; margin: 20px 0;">
            <div style="font-size: 16px; font-weight: bold; color: {score_color}; text-transform: uppercase; margin-bottom: 8px;">
                {'🌐 AI VERIFIED AGAINST LIVE GUIDELINES' if st.session_state.get('mc_live_verified') else '📄 AI READINESS SCORE'}
            </div>
            <div style="font-size: 48px; font-weight: bold; color: {score_color};">{score_emoji} {score}/100</div>
            <div style="font-size: 20px; color: {score_color}; margin-top: 8px;">{result.get('overall_verdict', '')}</div>
        </div>
        """, unsafe_allow_html=True)
        
        # Sub-scores
        col_s1, col_s2, col_s3 = st.columns(3)
        abs_fb = result.get("abstract_feedback", {})
        str_fb = result.get("structure_feedback", {})
        cnt_fb = result.get("content_feedback", {})
        
        col_s1.metric("Abstract", f"{abs_fb.get('score', '–')}/100")
        col_s2.metric("Structure", f"{str_fb.get('score', '–')}/100")
        col_s3.metric("Content", f"{cnt_fb.get('score', '–')}/100")
        
        # Journal Fit Assessment
        if result.get("journal_fit_assessment"):
            st.info(f"📚 **Journal Fit:** {result['journal_fit_assessment']}")
        
        st.divider()
        
        # Detailed Feedback Tabs
        tab1, tab2, tab3, tab4 = st.tabs(["📋 Action Items", "📝 Abstract", "🏗️ Structure", "✅ Compliance"])
        
        with tab1:
            st.markdown("### 🎯 Action Items")
            action_items = result.get("action_items", [])
            if action_items:
                for i, action in enumerate(action_items, 1):
                    st.markdown(f"**{i}.** {action}")
            else:
                st.success("No critical action items — your manuscript looks ready!")
        
        with tab2:
            st.markdown("### 📝 Abstract Feedback")
            if abs_fb.get("issues"):
                for issue in abs_fb["issues"]:
                    st.warning(issue)
            if abs_fb.get("suggestion"):
                st.info(f"💡 **Suggestion:** {abs_fb['suggestion']}")
        
        with tab3:
            st.markdown("### 🏗️ Structure Feedback")
            if str_fb.get("missing_critical"):
                st.error(f"❌ **Missing (Critical):** {', '.join(str_fb['missing_critical'])}")
            if str_fb.get("missing_recommended"):
                st.warning(f"⚠️ **Missing (Recommended):** {', '.join(str_fb['missing_recommended'])}")
            if str_fb.get("suggestion"):
                st.info(f"💡 **Suggestion:** {str_fb['suggestion']}")
            if not str_fb.get("missing_critical") and not str_fb.get("missing_recommended"):
                st.success("All expected sections are present!")
        
        with tab4:
            st.markdown("### ✅ Compliance Checklist")
            checklist = result.get("compliance_checklist", [])
            if checklist:
                for chk_item in checklist:
                    item_name = chk_item.get("item", "")
                    item_status = chk_item.get("status", "unknown")
                    item_note = chk_item.get("note", "")
                    if item_status == "pass":
                        st.markdown(f"✅ **{item_name}** — {item_note}")
                    elif item_status == "fail":
                        st.markdown(f"❌ **{item_name}** — {item_note}")
                    else:
                        st.markdown(f"⚠️ **{item_name}** — {item_note}")
            else:
                st.info("No compliance data available.")
        
        # Content strengths and weaknesses
        st.divider()
        col_sw1, col_sw2 = st.columns(2)
        with col_sw1:
            st.markdown("### 💪 Strengths")
            strengths = cnt_fb.get("strengths", [])
            if strengths:
                for s in strengths:
                    st.markdown(f"✅ {s}")
            else:
                st.info("Run the analysis to identify strengths.")
        with col_sw2:
            st.markdown("### ⚠️ Areas for Improvement")
            weaknesses = cnt_fb.get("weaknesses", [])
            if weaknesses:
                for w in weaknesses:
                    st.markdown(f"🔸 {w}")
            else:
                st.success("No significant issues identified.")
        
        # Download checker report
        st.divider()
        st.markdown("### 📥 Download Report")
        
        pdf_report = generate_readiness_pdf(result, mc_journal)
        st.download_button(
            label="📄 Download Full Readiness Report (PDF)",
            data=pdf_report,
            file_name=f"manuscripthub_readiness_{mc_journal.replace(' ', '_')}_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            use_container_width=True,
            key="download_mc_pdf_btn"
        )
        
        # Link to submit directly to the journal
        submit_meta = JOURNAL_METADATA.get(mc_journal, {})
        submit_url = submit_meta.get("homepage_url", submit_meta.get("website", ""))
        if submit_url:
            st.markdown("---")
            st.markdown(f"""
            <div style="text-align: center; padding: 16px; background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); border-radius: 12px; margin-top: 12px;">
                <a href="{submit_url}" target="_blank" style="color: white; text-decoration: none; font-size: 18px; font-weight: bold;">
                    🚀 Ready to Submit? Visit {mc_journal} →
                </a>
                <div style="color: #dbeafe; font-size: 13px; margin-top: 6px;">Opens the journal's website where you can find author guidelines and submission portal</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        # Show feature overview when no result yet
        st.markdown("---")
        col_feat1, col_feat2, col_feat3, col_feat4 = st.columns(4)
        with col_feat1:
            st.markdown("""
            #### 📤 Upload & Analyze
            Upload your full paper (PDF or Word) and we'll auto-extract structure, word count, and sections.
            """)
        with col_feat2:
            st.markdown("""
            #### 📊 Readiness Score
            Get a 0-100% score showing how ready your manuscript is for your **specific** target journal.
            """)
        with col_feat3:
            st.markdown("""
            #### ✍️ Actionable Fixes
            Receive journal-specific suggestions like "Shorten abstract", "Add JEL codes", "Format references".
            """)
        with col_feat4:
            st.markdown("""
            #### ✅ Compliance Check
            Journal-specific review of ethics, formatting, data availability, and more.
            """)

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

### 📄 Manuscript Checker — Now Live!
Upload your manuscript (PDF or Word) and get an **instant journal-specific readiness assessment**. Features include:
- **Document upload** — auto-extraction of structure, word count, sections, and references
- **Journal-specific analysis** — compliance checks tailored to your target journal's requirements
- **Compliance checklist** — formatting, word limits, references, ethics, data availability, figures, cover letter
- **Actionable fixes** — "Shorten abstract to 200 words", "Add JEL codes", "Include data availability statement"
- **Readiness score** — 0–100% per journal, with a clear path to 100%
- **Seamless integration** — click "Check Readiness" on any Journal Finder result to go straight to the checker

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