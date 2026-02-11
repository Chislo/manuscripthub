@echo off
title ManuscriptHub Launcher

echo Starting Journal Finder (Streamlit)...
start "Journal Finder - Streamlit" cmd /k "call venv\Scripts\activate && streamlit run app_streamlit.py"

echo.
echo Starting Manuscript Checker (Gradio - Coming Soon)...
start "Manuscript Checker - Gradio" cmd /k "call venv\Scripts\activate && python app_gradio.py"

echo.
echo Both apps are launching...
echo.
echo - Journal Finder: http://localhost:8501
echo - Manuscript Checker (Coming Soon): http://localhost:7860
echo.
pause