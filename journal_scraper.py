import re
import json
import time
from typing import Dict, Any, Optional
import streamlit as st
import requests
from bs4 import BeautifulSoup

def find_guidelines_url(journal_name: str, homepage: Optional[str] = None) -> Optional[str]:
    """
    Attempts to find the direct 'Information for Authors' or 'Submission Guidelines' URL
    for a given journal using the homepage or a search query.
    """
    # If we have a homepage, try to find links on it first
    if homepage and homepage.startswith("http"):
        try:
            response = requests.get(homepage, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                links = soup.find_all('a', href=True)
                
                # Priority keywords for guidelines
                keywords = ["submission", "author", "guideline", "instruct", "prepare", "manuscript", "policy"]
                for link in links:
                    text = link.get_text().lower()
                    href = link['href'].lower()
                    if any(kw in text for kw in keywords) or any(kw in href for kw in keywords):
                        # Ensure absolute URL
                        target = link['href']
                        if not target.startswith("http"):
                            from urllib.parse import urljoin
                            target = urljoin(homepage, target)
                        return target
        except Exception as e:
            print(f"Error scraping homepage {homepage}: {e}")

    # Fallback: We can't use search_web tool directly in a background function unless provided
    # or we can use a library if available. Assuming we want to use the agent's capability
    # to find this, we might pass it as a parameter or just return the homepage.
    return homepage

def extract_requirements_from_text(text: str, journal_name: str, llm_func) -> Dict[str, Any]:
    """
    Uses the LLM to extract a structured requirements matrix from raw guideline text.
    """
    
    prompt = f"""
    You are an expert editorial assistant. Extract specific submission requirements for the journal '{journal_name}' from the following text excerpt.
    
    TEXT:
    ---
    {text[:6000]}
    ---
    
    EXTRACT THE FOLLOWING (if mentioned):
    1. Word count limits (Abstract, Main Content, Total).
    2. Citation Style (APA, Harvard, Vancouver, Chicago, etc.).
    3. Required sections (e.g., JEL codes, Disclosure Statement, Data Availability).
    4. Formatting (Font size, Spacing, Margins).
    5. Cover Letter requirement (Mandatory, Optional, Not required).
    6. Review type (Double-blind, Single-blind, Open).
    7. Any other critical "desk-rejection" criteria.
    
    Return ONLY valid JSON.
    Format:
    {{
      "word_limits": {{ "abstract": "...", "main": "...", "total": "..." }},
      "citation_style": "...",
      "required_sections": ["...", "..."],
      "formatting": {{ "font": "...", "spacing": "...", "margins": "..." }},
      "cover_letter": "...",
      "review_type": "...",
      "critical_rules": ["...", "..."]
    }}
    """
    
    raw_json = llm_func(prompt, temperature=0.1)
    try:
        # Simple extraction of JSON from response
        match = re.search(r'\{[\s\S]*\}', raw_json)
        if match:
            return json.loads(match.group())
    except:
        pass
    return {{}}
