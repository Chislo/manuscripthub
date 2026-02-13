# ManuscriptHub 🚀

**Free AI-powered academic journal finder and manuscript checker** for researchers in Economics, Law, Finance, Business, Medicine, STEM, Social Sciences, and all academic disciplines.

🌐 **Live App**: [journal-matcher.streamlit.app](https://journal-matcher.streamlit.app)

## Features
- **AI Journal Finder**: Enter your paper title and abstract — get ranked journal recommendations with fit scores, prestige (SJR/Quartile), review speed, and acceptance rates.
- **Manuscript Checker**: Upload your paper (PDF/DOCX) and check it against real journal guidelines before submitting.
- **Hybrid Intelligence**: Combination of a curated Economics/Law/Finance database (1,800+ journals) and Google Gemini AI for universal field support.
- **Precision Filters**: Hard filters for Scopus indexation, target quartiles (Q1-Q4), and cost models (No submission fee, No APC, Diamond OA).
- **Completely Free**: No sign-up, no fees, no limits. Built for researchers, by researchers.

## Live Deployment (Cloud)
This app is deployed on **Streamlit Community Cloud** at [journal-matcher.streamlit.app](https://journal-matcher.streamlit.app).
1. Set your `GEMINI_API_KEY` in the Streamlit Secrets dashboard.
2. The app will automatically use Gemini-Flash for fast, zero-cost cloud recommendations.

## Local Setup
1. `python -m venv venv` and `venv\Scripts\activate`
2. `pip install -r requirements.txt`
3. (Optional) Create `.streamlit/secrets.toml` with `GEMINI_API_KEY = "your_key"` for cloud-parity locally.
4. Run: `streamlit run app_streamlit.py`

## License
ManuscriptHub is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.

Built by Chisom Ubabukoh, Ph.D (@Chylo360) 🎓
