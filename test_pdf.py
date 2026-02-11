import datetime
from fpdf import FPDF

def fit_label(score):
    if score >= 0.7: return "Excellent fit"
    if score >= 0.55: return "Strong fit"
    if score >= 0.4: return "Moderate fit"
    return "Weak fit"

def generate_pdf_report(recommendations):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", style="B", size=16)
    pdf.cell(0, 10, "ManuscriptHub - Test Report", ln=True, align="C")
    pdf.ln(10)
    for item in recommendations:
        pdf.set_font("Arial", style="B", size=12)
        pdf.cell(0, 8, f"{item['rank']}. {item['journal']}", ln=True)
        pdf.set_font("Arial", size=10)
        fit_txt = fit_label(item.get('fit_score', 0))
        metrics = f"Fit: {item.get('fit_score', 0):.0%} ({fit_txt})"
        pdf.cell(0, 6, metrics, ln=True)
        pdf.multi_cell(0, 6, f"Reason: {item['reason']}")
        pdf.ln(5)
    return pdf.output(dest='S')

# Test
recs = [{
    "rank": 1,
    "journal": "Test Journal of AI",
    "fit_score": 0.9,
    "reason": "This is a test reason for the PDF generation."
}]

try:
    output = generate_pdf_report(recs)
    print(f"PDF local test success. Output length: {len(output)}")
except Exception as e:
    print(f"PDF local test failed: {e}")
