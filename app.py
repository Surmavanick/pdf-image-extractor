import os
from flask import Flask, request, render_template_string, send_file
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
SEGMENT_FOLDER = os.path.join(OUTPUT_FOLDER, "segments")

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["OUTPUT_FOLDER"] = OUTPUT_FOLDER
app.config["SEGMENT_FOLDER"] = SEGMENT_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(SEGMENT_FOLDER, exist_ok=True)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>ECG PDF Cleaner & Segmenter</title>
  <style>
    body { font-family: sans-serif; padding: 24px; max-width: 900px; margin: auto; }
    .btn { padding: 8px 14px; border: 1px solid #ddd; background: #f7f7f7; cursor: pointer; border-radius: 8px; }
    .card { border: 1px solid #eee; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
  </style>
</head>
<body>
  <h2>ატვირთე ECG PDF</h2>
  <div class="card">
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="pdf_file" accept="application/pdf" required>
      <button class="btn" type="submit">გაწმენდა და სეგმენტაცია</button>
    </form>
  </div>

  {% if cleaned_pdf %}
    <div class="card">
      <h3>🧹 გაწმენდილი PDF</h3>
      <p><a href="{{ cleaned_pdf }}">ჩამოტვირთე ტექსტის გარეშე PDF</a></p>
    </div>
  {% endif %}

  {% if segments %}
    <div class="card">
      <h3>📈 სეგმენტირებული არხები (PDF)</h3>
      <ul>
        {% for seg in segments %}
          <li><a href="{{ seg }}">{{ seg.split('/')[-1] }}</a></li>
        {% endfor %}
      </ul>
    </div>
  {% endif %}
</body>
</html>
"""


def remove_text_from_pdf(input_pdf, output_pdf):
    """Removes all text from PDF using redaction while keeping vector graphics."""
    doc = fitz.open(input_pdf)
    for page in doc:
        words = page.get_text("words")
        if not words:
            continue
        for word in words:
            rect = fitz.Rect(word[:4])
            page.add_redact_annot(rect, fill=None)
        page.apply_redactions()
    doc.set_metadata({})
    doc.save(output_pdf, garbage=4, deflate=True, clean=True)
    doc.close()


def segment_vector_ecg(input_pdf, output_dir):
    """Splits the ECG page into 12 vector-based PDF segments (I–V6)."""
    os.makedirs(output_dir, exist_ok=True)
    leads = ["I", "II", "III", "aVR", "aVL", "aVF",
             "V1", "V2", "V3", "V4", "V5", "V6"]

    doc = fitz.open(input_pdf)
    page = doc[0]
    page_rect = page.rect
    segment_height = page_rect.height / len(leads)
    width = page_rect.width

    segment_files = []

    for i, lead in enumerate(leads):
        y0 = page_rect.y0 + i * segment_height
        y1 = y0 + segment_height
        clip_rect = fitz.Rect(page_rect.x0, y0, page_rect.x1, y1)

        new_pdf = fitz.open()
        new_page = new_pdf.new_page(width=width, height=segment_height)
        new_page.show_pdf_page(new_page.rect, doc, 0, clip=clip_rect)

        seg_path = os.path.join(output_dir, f"{lead}.pdf")
        new_pdf.save(seg_path)
        new_pdf.close()
        segment_files.append(f"/{seg_path}")

    return segment_files


@app.route("/", methods=["GET", "POST"])
def index():
    cleaned_pdf = None
    segments = []

    if request.method == "POST":
        file = request.files.get("pdf_file")
        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            base_no_ext = os.path.splitext(filename)[0]
            cleaned_pdf_name = f"{base_no_ext}_no_text.pdf"
            cleaned_pdf_path = os.path.join(app.config["OUTPUT_FOLDER"], cleaned_pdf_name)

            # 1️⃣ Clean text
            remove_text_from_pdf(filepath, cleaned_pdf_path)
            cleaned_pdf = f"/outputs/{cleaned_pdf_name}"

            # 2️⃣ Vector segmentation
            segment_output_dir = os.path.join(app.config["SEGMENT_FOLDER"], base_no_ext)
            segments = segment_vector_ecg(cleaned_pdf_path, segment_output_dir)

    return render_template_string(HTML_TEMPLATE, cleaned_pdf=cleaned_pdf, segments=segments)


@app.route("/outputs/<path:filename>")
def download_output(filename):
    return send_file(os.path.join(app.config["OUTPUT_FOLDER"], filename), as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
