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
  <title>ECG Vector Segmenter (Adaptive)</title>
  <style>
    body { font-family: sans-serif; padding: 24px; max-width: 900px; margin: auto; }
    .btn { padding: 8px 14px; border: 1px solid #ddd; background: #f7f7f7; cursor: pointer; border-radius: 8px; }
    .card { border: 1px solid #eee; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
    pre { background: #fafafa; border: 1px solid #eee; padding: 10px; border-radius: 8px; }
  </style>
</head>
<body>
  <h2>ატვირთე ECG PDF</h2>
  <div class="card">
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="pdf_file" accept="application/pdf" required>
      <button class="btn" type="submit">გაწმენდა და ადაპტური სეგმენტაცია</button>
    </form>
  </div>

  {% if cleaned_pdf %}
    <div class="card">
      <h3>🧹 ტექსტის გარეშე PDF</h3>
      <p><a href="{{ cleaned_pdf }}" download>ჩამოტვირთე გაწმენდილი PDF</a></p>
    </div>
  {% endif %}

  {% if segments %}
    <div class="card">
      <h3>📈 ECG სეგმენტები (ვექტორული PDF)</h3>
      <ul>
        {% for seg in segments %}
          <li><a href="{{ seg }}" download>{{ seg.split('/')[-1] }}</a></li>
        {% endfor %}
      </ul>
    </div>
  {% endif %}

  {% if logs %}
    <div class="card">
      <h3>📜 ლოგები</h3>
      <pre>{{ logs }}</pre>
    </div>
  {% endif %}
</body>
</html>
"""

# -------- TEXT REMOVAL (vector safe) --------
def remove_text_from_pdf(input_pdf, output_pdf):
    doc = fitz.open(input_pdf)
    for page in doc:
        words = page.get_text("words")
        for w in words:
            rect = fitz.Rect(w[:4])
            page.add_redact_annot(rect, fill=None)
        page.apply_redactions()
    doc.set_metadata({})
    doc.save(output_pdf, clean=True, deflate=True, garbage=4)
    doc.close()

# -------- ADAPTIVE SEGMENTATION (vector) --------
def adaptive_vector_segmentation(pdf_path, out_dir, logs, padding=15):
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    page = doc[0]

    drawings = page.get_drawings()
    logs.append(f"დოკუმენტში მოიძებნა {len(drawings)} drawing ობიექტი")

    # ECG path filter — long + thin
    ecg_paths = [d for d in drawings if (d["rect"].width > 200 and d["rect"].height < 50)]
    logs.append(f"ECG path-ების რაოდენობა: {len(ecg_paths)}")

    if not ecg_paths:
        logs.append("⚠️ ECG path ვერ მოიძებნა — შეამოწმე PDF ფორმატი.")
        return []

    # Group by Y proximity
    ecg_paths.sort(key=lambda d: d["rect"].y0)
    groups = []
    threshold = 25  # clustering sensitivity
    for d in ecg_paths:
        y_center = (d["rect"].y0 + d["rect"].y1) / 2
        if not groups or abs(y_center - groups[-1]["center"]) > threshold:
            groups.append({"center": y_center, "items": [d]})
        else:
            groups[-1]["items"].append(d)

    logs.append(f"დაფიქსირდა {len(groups)} სავარაუდო ECG ზოლი")

    segment_urls = []
    for i, g in enumerate(groups):
        rects = [d["rect"] for d in g["items"]]
        top = min(r.y0 for r in rects) - padding
        bottom = max(r.y1 for r in rects) + padding
        left = min(r.x0 for r in rects)
        right = max(r.x1 for r in rects)
        clip = fitz.Rect(left, top, right, bottom)

        new_pdf = fitz.open()
        new_page = new_pdf.new_page(width=clip.width, height=clip.height)
        new_page.show_pdf_page(new_page.rect, doc, 0, clip=clip)
        seg_path = os.path.join(out_dir, f"lead_{i+1}.pdf")
        new_pdf.save(seg_path, clean=True, deflate=True)
        new_pdf.close()

        rel_path = f"/segments/{os.path.basename(out_dir)}/lead_{i+1}.pdf"
        segment_urls.append(rel_path)

    doc.close()
    logs.append(f"✅ სეგმენტაცია დასრულდა ({len(segment_urls)} ფაილი)")
    return segment_urls


# -------- FLASK ROUTES --------
@app.route("/", methods=["GET", "POST"])
def index():
    cleaned_pdf = None
    segments = []
    logs = []

    if request.method == "POST":
        f = request.files.get("pdf_file")
        if f and f.filename:
            filename = secure_filename(f.filename)
            in_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            f.save(in_path)
            base_name = os.path.splitext(filename)[0]

            # Step 1 — Clean text
            cleaned_name = f"{base_name}_no_text.pdf"
            cleaned_path = os.path.join(app.config["OUTPUT_FOLDER"], cleaned_name)
            logs.append(f"📄 ტექსტის მოშლა: {filename}")
            remove_text_from_pdf(in_path, cleaned_path)
            cleaned_pdf = f"/outputs/{cleaned_name}"
            logs.append("🧹 ტექსტისგან გასუფთავება დასრულებულია.")

            # Step 2 — Adaptive vector segmentation
            logs.append("📈 ECG სეგმენტაცია მიმდინარეობს (ადაპტური)...")
            seg_dir = os.path.join(app.config["SEGMENT_FOLDER"], base_name)
            segments = adaptive_vector_segmentation(cleaned_path, seg_dir, logs)

    return render_template_string(HTML_TEMPLATE, cleaned_pdf=cleaned_pdf, segments=segments, logs="\n".join(logs))


@app.route("/outputs/<path:filename>")
def download_output(filename):
    return send_file(os.path.join(app.config["OUTPUT_FOLDER"], filename), as_attachment=True)


@app.route("/segments/<path:filename>")
def download_segment(filename):
    return send_file(os.path.join(app.config["SEGMENT_FOLDER"], filename), as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
