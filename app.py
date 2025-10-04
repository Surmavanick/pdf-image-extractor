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
        # ტექსტის ამოღების ნაცვლად, პირდაპირ ვშლით ყველა ტექსტურ ობიექტს.
        # ეს უფრო საიმედოა, ვიდრე სიტყვების სათითაოდ მონიშვნა.
        for text_inst in page.get_text_instances():
             page.add_redact_annot(text_inst[:4], fill=None)
        page.apply_redactions()
    doc.set_metadata({})
    doc.save(output_pdf, garbage=4, deflate=True, clean=True)
    doc.close()


def segment_vector_ecg_by_extraction(input_pdf, output_dir):
    """
    Splits the ECG into segments by extracting vector paths based on their color and position.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. პარამეტრები (შეიძლება დაგჭირდეთ დაკონფიგურირება)
    # ეკგ ხაზის ფერი (RGB, 0-1 შუალედში). თქვენს სურათზე ხაზი მუქია, სავარაუდოდ შავი.
    TARGET_COLOR = (0, 0, 0) 
    COLOR_TOLERANCE = 0.1 # ცდომილება ფერის ამოსაცნობად
    
    doc = fitz.open(input_pdf)
    if not doc:
        return []
    page = doc[0]
    
    # 2. ეკგ ხაზების ამოღება ფერის მიხედვით
    drawings = page.get_drawings()
    ecg_paths = []
    for path in drawings:
        if path.get("stroke_color") and path.get("type") == "s":
            color = path["stroke_color"]
            if (abs(color[0] - TARGET_COLOR[0]) < COLOR_TOLERANCE and
                abs(color[1] - TARGET_COLOR[1]) < COLOR_TOLERANCE and
                abs(color[2] - TARGET_COLOR[2]) < COLOR_TOLERANCE):
                y_coords = [p.y for item in path["items"] for p in item[1:]]
                if y_coords:
                    avg_y = sum(y_coords) / len(y_coords)
                    ecg_paths.append({"path": path, "avg_y": avg_y})

    if not ecg_paths:
        print("ეკგ ხაზები ვერ მოიძებნა ფერის მიხედვით.")
        return []

    # 3. ხაზების დაჯგუფება ვერტიკალური პოზიციის მიხედვით
    ecg_paths.sort(key=lambda p: p["avg_y"])
    
    groups = []
    if ecg_paths:
        current_group = [ecg_paths[0]]
        for i in range(1, len(ecg_paths)):
            if ecg_paths[i]["avg_y"] - ecg_paths[i-1]["avg_y"] > 20:
                groups.append(current_group)
                current_group = [ecg_paths[i]]
            else:
                current_group.append(ecg_paths[i])
        groups.append(current_group)

    # 4. თითოეული ჯგუფის (განხრის) შენახვა ცალკე PDF-ად
    segment_files = []
    leads = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6", "Rhythm_Strip"]
    
    for i, group in enumerate(groups):
        if i >= len(leads): break
        lead_name = leads[i]
        
        new_pdf = fitz.open()
        
        all_points = [p for p_info in group for item in p_info["path"]["items"] for p in item[1:]]
        if not all_points: continue

        min_x = min(p.x for p in all_points)
        max_x = max(p.x for p in all_points)
        min_y = min(p.y for p in all_points)
        max_y = max(p.y for p in all_points)

        padding = 10
        width = (max_x - min_x) + 2 * padding
        height = (max_y - min_y) + 2 * padding
        
        new_page = new_pdf.new_page(width=width, height=height)
        
        for path_info in group:
            for item in path_info["path"]["items"]:
                offset = fitz.Point(min_x - padding, min_y - padding)
                if item[0] == "l":
                    new_page.draw_line(item[1] - offset, item[2] - offset, color=TARGET_COLOR)
                elif item[0] == "c":
                    new_page.draw_bezier(item[1] - offset, item[2] - offset, item[3] - offset, item[4] - offset, color=TARGET_COLOR)

        seg_path = os.path.join(output_dir, f"{lead_name}.pdf")
        new_pdf.save(seg_path)
        new_pdf.close()
        segment_files.append(f"/{seg_path}")
        
    doc.close()
    return segment_files


@app.route("/", methods=["GET", "POST"])
def index():
    cleaned_pdf = None
    segments = []

    if request.method == "POST":
        file = request.files.get("pdf_file")
        if file and file.filename:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            base_no_ext = os.path.splitext(filename)[0]
            cleaned_pdf_name = f"{base_no_ext}_no_text.pdf"
            cleaned_pdf_path = os.path.join(app.config["OUTPUT_FOLDER"], cleaned_pdf_name)

            # 1️⃣ ტექსტის გაწმენდა
            remove_text_from_pdf(filepath, cleaned_pdf_path)
            cleaned_pdf = f"/outputs/{cleaned_pdf_name}"

            # 2️⃣ ვექტორული სეგმენტაცია (განახლებული ფუნქციის გამოძახება)
            segment_output_dir = os.path.join(app.config["SEGMENT_FOLDER"], base_no_ext)
            segments = segment_vector_ecg_by_extraction(cleaned_pdf_path, segment_output_dir)

    return render_template_string(HTML_TEMPLATE, cleaned_pdf=cleaned_pdf, segments=segments)


@app.route("/outputs/<path:filename>")
def download_output(filename):
    return send_file(os.path.join(app.config["OUTPUT_FOLDER"], filename), as_attachment=True)
    
@app.route("/outputs/segments/<path:filename>")
def download_segment(filename):
    # This route is needed to serve files from subdirectories in 'outputs'
    return send_file(os.path.join(app.config["OUTPUT_FOLDER"], "segments", filename), as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
