import os
from flask import Flask, request, render_template_string, send_file
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["OUTPUT_FOLDER"] = OUTPUT_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>ECG PDF Cleaner</title>
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
      <button class="btn" type="submit">გაწმენდა</button>
    </form>
  </div>

  {% if cleaned_pdf %}
    <div class="card">
      <h3>🧹 გაწმენდილი PDF</h3>
      <p><a href="{{ cleaned_pdf }}">ჩამოტვირთე გაწმენდილი ECG PDF</a></p>
    </div>
  {% endif %}
</body>
</html>
"""

def pdf_to_images_only(input_pdf, output_pdf, dpi=300):
    """Convert each page into image-only PDF (no text, no hidden objects)."""
    doc = fitz.open(input_pdf)
    new_doc = fitz.open()

    zoom = dpi / 72  # scale factor (72 is default PDF DPI)
    mat = fitz.Matrix(zoom, zoom)

    for page in doc:
        # გვერდის რენდერინგი სურათად
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")

        # ახალი PDF გვერდი მხოლოდ ამ სურათით
        rect = fitz.Rect(0, 0, pix.width, pix.height)
        new_page = new_doc.new_page(width=pix.width, height=pix.height)
        new_page.insert_image(rect, stream=img_bytes)

    # საბოლოო შენახვა
    new_doc.save(output_pdf, deflate=True, garbage=4, clean=True)
    new_doc.close()

@app.route("/", methods=["GET", "POST"])
def index():
    cleaned_pdf = None

    if request.method == "POST":
        file = request.files.get("pdf_file")
        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            base_no_ext = os.path.splitext(filename)[0]
            cleaned_pdf_name = f"{base_no_ext}_cleaned.pdf"
            cleaned_pdf_path = os.path.join(app.config["OUTPUT_FOLDER"], cleaned_pdf_name)

            pdf_to_images_only(filepath, cleaned_pdf_path, dpi=300)
            cleaned_pdf = f"/outputs/{cleaned_pdf_name}"

    return render_template_string(HTML_TEMPLATE, cleaned_pdf=cleaned_pdf)

@app.route("/outputs/<path:filename>")
def download_output(filename):
    return send_file(os.path.join(app.config["OUTPUT_FOLDER"], filename), as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
