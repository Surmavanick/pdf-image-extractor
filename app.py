import os
from flask import Flask, request, render_template_string, send_from_directory
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF

# --- ძირითადი კონფიგურაცია ---
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
SEGMENT_FOLDER = os.path.join(OUTPUT_FOLDER, "segments")

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["OUTPUT_FOLDER"] = OUTPUT_FOLDER
app.config["SEGMENT_FOLDER"] = SEGMENT_FOLDER

# --- ფოლდერების შექმნა გაშვებისას ---
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(SEGMENT_FOLDER, exist_ok=True)

# --- ვებ-გვერდის HTML შაბლონი ---
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
      <p><a href="{{ cleaned_pdf }}" download>ჩამოტვირთე ტექსტის გარეშე PDF</a></p>
    </div>
  {% endif %}

  {% if segments %}
    <div class="card">
      <h3>📈 სეგმენტირებული არხები (PDF)</h3>
      <ul>
        {% for seg in segments %}
          <li><a href="{{ seg.url }}" download>{{ seg.name }}</a></li>
        {% endfor %}
      </ul>
    </div>
  {% endif %}
</body>
</html>
"""

# --- დამხმარე ფუნქციები ---

def remove_text_from_pdf(input_pdf, output_pdf):
    """Removes all text from a PDF by applying redactions."""
    doc = fitz.open(input_pdf)
    for page in doc:
        # ვიყენებთ get_text("words")-ს, რომელიც სტაბილურად მუშაობს
        words = page.get_text("words")
        for word in words:
            rect = fitz.Rect(word[:4])
            page.add_redact_annot(rect)
        
        # ვშლით მონიშნულ ტექსტს
        page.apply_redactions()
    
    # ვინახავთ გასუფთავებულ ფაილს
    doc.save(output_pdf, garbage=4, deflate=True, clean=True)
    doc.close()


def segment_vector_ecg_by_extraction(input_pdf, output_dir):
    """
    Splits the ECG into segments by extracting vector paths based on their color and position.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    TARGET_COLOR = (0, 0, 0) 
    COLOR_TOLERANCE = 0.1
    
    doc = fitz.open(input_pdf)
    if not doc or doc.page_count == 0:
        return []
    page = doc[0]
    
    drawings = page.get_drawings()
    ecg_paths = []
    for path in drawings:
        # ვამოწმებთ, რომ ობიექტს აქვს ფერი და არის ხაზი
        if path.get("stroke_color") and path.get("type") == "s":
            color = path["stroke_color"]
            if (abs(color[0] - TARGET_COLOR[0]) < COLOR_TOLERANCE and
                abs(color[1] - TARGET_COLOR[1]) < COLOR_TOLERANCE and
                abs(color[2] - TARGET_COLOR[2]) < COLOR_TOLERANCE):
                y_coords = [p.y for item in path["items"] for p in item[1:] if isinstance(p, fitz.Point)]
                if y_coords:
                    avg_y = sum(y_coords) / len(y_coords)
                    ecg_paths.append({"path": path, "avg_y": avg_y})

    if not ecg_paths:
        print("ეკგ ხაზები ვერ მოიძებნა ფერის მიხედვით.")
        doc.close()
        return []

    ecg_paths.sort(key=lambda p: p["avg_y"])
    
    groups = []
    if ecg_paths:
        current_group = [ecg_paths[0]]
        for i in range(1, len(ecg_paths)):
            # თუ ორ ხაზს შორის ვერტიკალური დაშორება დიდია, ეს ახალი ჯგუფია
            if ecg_paths[i]["avg_y"] - current_group[-1]["avg_y"] > 20: 
                groups.append(current_group)
                current_group = []
            current_group.append(ecg_paths[i])
        groups.append(current_group)

    segment_files_info = []
    leads = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6", "Rhythm_Strip"]
    
    for i, group in enumerate(groups):
        if i >= len(leads): break
        lead_name = leads[i]
        
        all_points = [p for p_info in group for item in p_info["path"]["items"] for p in item[1:] if isinstance(p, fitz.Point)]
        if not all_points: continue

        min_x = min(p.x for p in all_points)
        max_x = max(p.x for p in all_points)
        min_y = min(p.y for p in all_points)
        max_y = max(p.y for p in all_points)

        padding = 10
        width = (max_x - min_x) + 2 * padding
        height = (max_y - min_y) + 2 * padding
        
        new_pdf = fitz.open()
        new_page = new_pdf.new_page(width=width, height=height)
        
        for path_info in group:
            for item in path_info["path"]["items"]:
                offset = fitz.Point(min_x - padding, min_y - padding)
                if item[0] == "l":
                    new_page.draw_line(item[1] - offset, item[2] - offset, color=TARGET_COLOR)
                elif item[0] == "c":
                    new_page.draw_bezier(item[1] - offset, item[2] - offset, item[3] - offset, item[4] - offset, color=TARGET_COLOR)

        relative_path = os.path.join(os.path.basename(output_dir), f"{lead_name}.pdf")
        full_path = os.path.join(output_dir, f"{lead_name}.pdf")
        new_pdf.save(full_path)
        new_pdf.close()
        
        segment_files_info.append({
            "name": f"{lead_name}.pdf",
            "url": f"/segments/{relative_path}"
        })
        
    doc.close()
    return segment_files_info


# --- ვებ-გვერდის ლოგიკა (Routes) ---

@app.route("/", methods=["GET", "POST"])
def index():
    cleaned_pdf_url = None
    segments_info = []

    if request.method == "POST":
        file = request.files.get("pdf_file")
        if file and file.filename:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            base_no_ext = os.path.splitext(filename)[0]
            
            # 1️⃣ ტექსტის გაწმენდა
            cleaned_pdf_name = f"{base_no_ext}_no_text.pdf"
            cleaned_pdf_path = os.path.join(app.config["OUTPUT_FOLDER"], cleaned_pdf_name)
            remove_text_from_pdf(filepath, cleaned_pdf_path)
            cleaned_pdf_url = f"/outputs/{cleaned_pdf_name}"

            # 2️⃣ ვექტორული სეგმენტაცია
            segment_output_dir = os.path.join(app.config["SEGMENT_FOLDER"], base_no_ext)
            segments_info = segment_vector_ecg_by_extraction(cleaned_pdf_path, segment_output_dir)

    return render_template_string(HTML_TEMPLATE, cleaned_pdf=cleaned_pdf_url, segments=segments_info)


@app.route("/outputs/<path:filename>")
def download_output(filename):
    """ფაილის გადმოწერა 'outputs' ფოლდერიდან."""
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename, as_attachment=True)
    
@app.route("/segments/<path:filename>")
def download_segment(filename):
    """სეგმენტის გადმოწერა 'segments' ქვედა ფოლდერიდან."""
    return send_from_directory(app.config["SEGMENT_FOLDER"], filename, as_attachment=True)


# --- აპლიკაციის გაშვება ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
