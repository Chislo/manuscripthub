# ManuscriptHub 🚀

AI-powered journal recommender for Economics, Law, and all academic disciplines.

## Features
- **Hybrid Intelligence**: Combination of a highly accurate Economics/Law database and global AI-knowledge (via Google Gemini) for universal field support.
- **Universal Journal Finder**: Supports Medicine, STEM, Social Sciences, Arts, Psychology, and more.
- **Precision Filters**: Hard filters for Scopus indexation, target quartiles (Q1-Q4), and cost models (Submission fees, APC, Diamond OA).
- **Aesthetic UI**: Smooth sidebar-main synchronization, high-visibility progress indicators, and responsive design.

## Live Deployment (Cloud)
This app is ready for deployment on **Streamlit Cloud**.
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
