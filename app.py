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
      <button class="btn" type="submit">ტექსტის წაშლა</button>
    </form>
  </div>

  {% if cleaned_pdf %}
    <div class="card">
      <h3>🧹 PDF ტექსტის გარეშე</h3>
      <p><a href="{{ cleaned_pdf }}">ჩამოტვირთე გაწმენდილი PDF</a></p>
    </div>
  {% endif %}
</body>
</html>
"""

def remove_text_from_pdf(input_pdf, output_pdf):
    """
    პოულობს და შლის ტექსტს PDF-დან redaction-ის გამოყენებით.
    ინარჩუნებს სხვა გრაფიკულ ელემენტებს.
    """
    doc = fitz.open(input_pdf)

    for page in doc:
        # ვიპოვოთ გვერდზე ყველა სიტყვა და მათი კოორდინატები
        words = page.get_text("words")
        if not words:
            continue

        # თითოეული სიტყვისთვის დავამატოთ redaction (წაშლის) მონიშვნა
        for word in words:
            # word[:4] არის სიტყვის კოორდინატები (მართკუთხედი)
            rect = fitz.Rect(word[:4])
            page.add_redact_annot(rect, fill=(1, 1, 1)) # fill=(1,1,1) თეთრი ფერით ავსებს

        # გამოვიყენოთ ყველა მონიშვნა, რაც საბოლოოდ შლის ტექსტს
        page.apply_redactions()

    # შევინახოთ გაწმენდილი დოკუმენტი
    doc.save(output_pdf, garbage=4, deflate=True, clean=True)
    doc.close()


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
            cleaned_pdf_name = f"{base_no_ext}_no_text.pdf"
            cleaned_pdf_path = os.path.join(app.config["OUTPUT_FOLDER"], cleaned_pdf_name)

            # ტექსტის წაშლის ახალი ფუნქციის გამოყენება
            remove_text_from_pdf(filepath, cleaned_pdf_path)
            cleaned_pdf = f"/outputs/{cleaned_pdf_name}"

    return render_template_string(HTML_TEMPLATE, cleaned_pdf=cleaned_pdf)


@app.route("/outputs/<path:filename>")
def download_output(filename):
    return send_file(os.path.join(app.config["OUTPUT_FOLDER"], filename), as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
