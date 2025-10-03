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
  <title>PDF Extractor</title>
  <style>
    body { font-family: sans-serif; padding: 24px; max-width: 900px; margin: auto; }
    .btn { padding: 8px 14px; border: 1px solid #ddd; background: #f7f7f7; cursor: pointer; border-radius: 8px; }
    .card { border: 1px solid #eee; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
  </style>
</head>
<body>
  <h2>ატვირთე PDF</h2>
  <div class="card">
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="pdf_file" accept="application/pdf" required>
      <button class="btn" type="submit">ამოღება</button>
    </form>
  </div>

  {% if text_file %}
    <div class="card">
      <h3>📄 ტექსტი</h3>
      <p><a href="{{ text_file }}">ჩამოტვირთე ტექსტი (TXT)</a></p>
    </div>
  {% endif %}

  {% if images %}
    <div class="card">
      <h3>📷 სურათები</h3>
      <ul>
      {% for img in images %}
        <li><a href="{{ img }}">სურათი {{ loop.index }}</a></li>
      {% endfor %}
      </ul>
    </div>
  {% endif %}

  {% if no_text_pdf %}
    <div class="card">
      <h3>🧹 ტექსტის გარეშე PDF</h3>
      <p><a href="{{ no_text_pdf }}">ჩამოტვირთე PDF ტექსტის გარეშე</a></p>
    </div>
  {% endif %}
</body>
</html>
"""

def remove_text_from_pdf(input_pdf, output_pdf):
    """შექმნის PDF-ს, სადაც გვერდები მხოლოდ სურათებად არის, საერთოდ არ აქვს ტექსტური ობიექტები."""
    doc = fitz.open(input_pdf)
    new_doc = fitz.open()

    for page in doc:
        # მაღალი ხარისხის გამოსახულება (300 DPI ეკვივალენტი)
        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
        img_bytes = pix.tobytes("png")

        rect = fitz.Rect(0, 0, pix.width, pix.height)
        new_page = new_doc.new_page(width=pix.width, height=pix.height)

        # ვამატებთ მხოლოდ სურათს, სხვა არაფერი
        new_page.insert_image(rect, stream=img_bytes)

    # ვასუფთავებთ ყველაფერს, რომ PDF-ში ძველი ობიექტები არ დარჩეს
    new_doc.save(output_pdf, garbage=4, deflate=True, clean=True)
    new_doc.close()

@app.route("/", methods=["GET", "POST"])
def index():
    text_file = None
    images = []
    no_text_pdf = None

    if request.method == "POST":
        file = request.files.get("pdf_file")
        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            base_no_ext = os.path.splitext(filename)[0]
            doc = fitz.open(filepath)

            # ტექსტის ამოღება TXT-ში
            text_output_name = f"{base_no_ext}_text.txt"
            text_output_path = os.path.join(app.config["OUTPUT_FOLDER"], text_output_name)
            with open(text_output_path, "w", encoding="utf-8") as f:
                for i, page in enumerate(doc):
                    f.write(f"--- Page {i+1} ---\n")
                    f.write(page.get_text("text"))
                    f.write("\n\n")
            text_file = f"/outputs/{text_output_name}"

            # ჩაშენებული სურათების ამოღება
            for page_index, page in enumerate(doc):
                for img_index, img in enumerate(page.get_images(full=True)):
                    xref = img[0]
                    pix = fitz.Pixmap(doc, xref)
                    img_filename = f"{base_no_ext}_p{page_index+1}_{img_index+1}.png"
                    img_path = os.path.join(app.config["OUTPUT_FOLDER"], img_filename)

                    if pix.n < 5:
                        pix.save(img_path)
                    else:
                        pix1 = fitz.Pixmap(fitz.csRGB, pix)
                        pix1.save(img_path)
                        pix1 = None
                    pix = None
                    images.append(f"/outputs/{img_filename}")

            # ტექსტის გარეშე PDF
            no_text_pdf_name = f"{base_no_ext}_no_text.pdf"
            no_text_pdf_path = os.path.join(app.config["OUTPUT_FOLDER"], no_text_pdf_name)
            remove_text_from_pdf(filepath, no_text_pdf_path)
            no_text_pdf = f"/outputs/{no_text_pdf_name}"

    return render_template_string(HTML_TEMPLATE, text_file=text_file, images=images, no_text_pdf=no_text_pdf)

@app.route("/outputs/<path:filename>")
def download_output(filename):
    return send_file(os.path.join(app.config["OUTPUT_FOLDER"], filename), as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
