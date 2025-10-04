import os
from collections import defaultdict
from flask import Flask, request, render_template_string, send_from_directory
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF

# --- Paths / config ---
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
SEGMENT_FOLDER = os.path.join(OUTPUT_FOLDER, "segments")

LEADS = ["I","II","III","aVR","aVL","aVF","V1","V2","V3","V4","V5","V6"]

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
  <title>ECG PDF Cleaner & Vector Segmenter</title>
  <style>
    body { font-family: sans-serif; padding: 24px; max-width: 900px; margin: auto; }
    .btn { padding: 8px 14px; border: 1px solid #ddd; background: #f7f7f7; cursor: pointer; border-radius: 8px; }
    .card { border: 1px solid #eee; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
    .logs { background: #fafafa; border: 1px solid #e5e5e5; padding: 10px; border-radius: 8px; font-family: monospace; white-space: pre-wrap; margin-top: 16px; max-height: 220px; overflow-y: auto;}
  </style>
</head>
<body>
  <h2>ატვირთე ECG PDF</h2>
  <div class="card">
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="pdf_file" accept="application/pdf" required>
      <button class="btn" type="submit">Clean + Segment (Vector)</button>
    </form>
  </div>

  {% if data and data.cleaned_pdf_url %}
    <div class="card">
      <h3>🧹 Cleaned PDF (no text)</h3>
      <p><a href="{{ data.cleaned_pdf_url }}" download>Download cleaned PDF</a></p>
    </div>
  {% endif %}

  {% if data and data.segment_urls %}
    <div class="card">
      <h3>📈 Segmented Leads (vector PDFs)</h3>
      <ul>
        {% for name, url in data.segment_urls %}
          <li><a href="{{ url }}" download>{{ name }}</a></li>
        {% endfor %}
      </ul>
    </div>
  {% endif %}

  {% if data and data.logs %}
    <div class="card">
      <h3>Logs</h3>
      <div class="logs">{{ data.logs }}</div>
    </div>
  {% endif %}
</body>
</html>
"""

# ---------- Text removal (vector intact) ----------
def remove_text_via_redaction(input_pdf: str, output_pdf: str):
    doc = fitz.open(input_pdf)
    for page in doc:
        words = page.get_text("words")  # [x0,y0,x1,y1,"text",...]
        for w in words:
            r = fitz.Rect(w[0], w[1], w[2], w[3])
            page.add_redact_annot(r, fill=None)  # remove text; keep background
        page.apply_redactions()
    # drop metadata too
    doc.set_metadata({})
    doc.save(output_pdf, clean=True, garbage=4, deflate=True)
    doc.close()

# ---------- Label-based grid detection ----------
def _extract_label_words(page, logs):
    want = set(LEADS)  # {"I","II","III","aVR","aVL","aVF","V1"...}
    found = []
    # use word extraction to avoid partial matches
    for w in page.get_text("words"):
        txt = w[4].strip()
        if txt in want:
            x0,y0,x1,y1 = w[0], w[1], w[2], w[3]
            found.append({"text": txt, "x": (x0+x1)/2.0, "y": (y0+y1)/2.0, "bbox": (x0,y0,x1,y1)})
    logs.append(f"Label words found: {len(found)}")
    # de-duplicate identical labels very close to each other
    dedup = []
    seen = []
    for f in sorted(found, key=lambda t:(t["text"], t["y"], t["x"])):
        key = (f["text"], round(f["x"],1), round(f["y"],1))
        if key in seen: 
            continue
        seen.append(key)
        dedup.append(f)
    logs.append(f"After de-dup: {len(dedup)}")
    return dedup

def _cluster_positions(vals, tol):
    """simple 1D clustering by distance tolerance; returns sorted cluster centers & members"""
    if not vals: 
        return []
    vals = sorted(vals)
    clusters = [[vals[0]]]
    for v in vals[1:]:
        if abs(v - clusters[-1][-1]) <= tol:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    centers = [sum(c)/len(c) for c in clusters]
    return sorted(centers)

def _compute_grid_from_labels(page, labels, logs):
    """infer 3 columns & 4 rows for 12-lead grid, plus rhythm II as bottom-most label"""
    pr = page.rect
    xs = [l["x"] for l in labels]
    ys = [l["y"] for l in labels]
    # tolerances proportional to page size
    col_tol = pr.width / 20.0
    row_tol = pr.height / 20.0
    col_centers = _cluster_positions(xs, col_tol)
    row_centers = _cluster_positions(ys, row_tol)
    logs.append(f"Column centers: {['%.1f'%c for c in col_centers]}")
    logs.append(f"Row centers: {['%.1f'%r for r in row_centers]}")

    # aim for 3 columns (I-II-III / aVR-aVL-aVF / V1-V2-V3 / V4-V5-V6)
    if len(col_centers) < 3:
        # fallback: evenly spaced 3 cols
        col_centers = [pr.x0 + pr.width*(1/6), pr.x0 + pr.width*(3/6), pr.x0 + pr.width*(5/6)]
    if len(row_centers) < 4:
        # try to remove the bottom rhythm II if present (largest y)
        if "II" in [l["text"] for l in labels]:
            y_sorted = sorted(ys)
            # take 4 cluster centers above  bottom-most
            top_ys = y_sorted[:-1] if len(y_sorted) >= 5 else y_sorted
            row_centers = _cluster_positions(top_ys, row_tol)
        # fallback: evenly spaced 4 rows
        while len(row_centers) < 4:
            row_centers = [pr.y0 + pr.height*(1/10), pr.y0 + pr.height*(3/10),
                           pr.y0 + pr.height*(5/10), pr.y0 + pr.height*(7/10)]

    # compute boundaries as midpoints
    def mid(a,b): return (a+b)/2.0
    col_centers = sorted(col_centers)[:3]
    row_centers = sorted(row_centers)[:4]

    col_bounds = [pr.x0,
                  mid(col_centers[0], col_centers[1]),
                  mid(col_centers[1], col_centers[2]),
                  pr.x1]
    row_bounds = [pr.y0,
                  mid(row_centers[0], row_centers[1]),
                  mid(row_centers[1], row_centers[2]),
                  mid(row_centers[2], row_centers[3]),
                  None]  # last will be set later

    # bottom rhythm II: pick the 'II' label with max y
    ii_labels = [l for l in labels if l["text"] == "II"]
    rhythm_top = None
    if ii_labels:
        bottom_ii = max(ii_labels, key=lambda t:t["y"])
        # rhythm top ~ midway between last grid row center and this II
        rhythm_top = mid(row_centers[-1], bottom_ii["y"])
    else:
        # if not found, assume rhythm occupies last 1/6th of page
        rhythm_top = pr.y0 + pr.height*5/6

    row_bounds[-1] = pr.y1  # full page bottom
    grid_bottom = rhythm_top

    # final rectangles for the 12 leads (4 rows x 3 cols)
    cells = {}
    grid_rows_tops = [pr.y0, row_bounds[1], row_bounds[2], row_bounds[3]]
    grid_rows_bottoms = [row_bounds[1], row_bounds[2], row_bounds[3], grid_bottom]

    names_grid = [
        ["I","II","III"],
        ["aVR","aVL","aVF"],
        ["V1","V2","V3"],
        ["V4","V5","V6"]
    ]

    rects = {}
    for r in range(4):
        top = grid_rows_tops[r]
        bottom = grid_rows_bottoms[r]
        for c in range(3):
            left = col_bounds[c]
            right = col_bounds[c+1]
            name = names_grid[r][c]
            rects[name] = fitz.Rect(left, top, right, bottom)

    # rhythm II rect
    rects["II_rhythm"] = fitz.Rect(pr.x0, grid_bottom, pr.x1, pr.y1)
    logs.append("Grid built from labels (with vector-safe clip boxes).")
    return rects

def segment_vector_with_labels(source_pdf: str, out_dir: str, logs):
    os.makedirs(out_dir, exist_ok=True)
    src = fitz.open(source_pdf)
    if src.page_count == 0:
        logs.append("ERROR: empty PDF.")
        src.close()
        return []

    page = src[0]
    labels = _extract_label_words(page, logs)

    # compute vector clip rectangles
    rects = _compute_grid_from_labels(page, labels, logs)

    # build each lead PDF by show_pdf_page (keeps vector content intact)
    outputs = []
    # 12 leads
    for name in LEADS:
        if name not in rects:
            # In case of two "II", grid II is already covered; we still produce it from grid slot.
            pass
        clip = rects.get(name)
        if clip is None:
            continue
        new_pdf = fitz.open()
        new_page = new_pdf.new_page(width=clip.width, height=clip.height)
        new_page.show_pdf_page(new_page.rect, src, 0, clip=clip)
        out_path = os.path.join(out_dir, f"{name}.pdf")
        new_pdf.save(out_path, clean=True, deflate=True)
        new_pdf.close()
        outputs.append((f"{name}.pdf", f"/segments/{os.path.basename(out_dir)}/{name}.pdf"))

    # rhythm II (optional)
    if "II_rhythm" in rects:
        clip = rects["II_rhythm"]
        new_pdf = fitz.open()
        new_page = new_pdf.new_page(width=clip.width, height=clip.height)
        new_page.show_pdf_page(new_page.rect, src, 0, clip=clip)
        out_path = os.path.join(out_dir, "II_rhythm.pdf")
        new_pdf.save(out_path, clean=True, deflate=True)
        new_pdf.close()
        outputs.append(("II_rhythm.pdf", f"/segments/{os.path.basename(out_dir)}/II_rhythm.pdf"))

    src.close()
    logs.append(f"Segments generated: {len(outputs)}")
    return outputs

# ---------- Fallback equal-grid segmentation (if labels fail completely) ----------
def segment_vector_fallback(source_pdf: str, out_dir: str, logs):
    os.makedirs(out_dir, exist_ok=True)
    src = fitz.open(source_pdf)
    p = src[0]
    pr = p.rect
    outputs = []
    # assume 4 rows x 3 cols for 12 leads, bottom 1/6 page for rhythm II
    grid_bottom = pr.y0 + pr.height*5/6
    rows = [pr.y0,
            pr.y0 + (grid_bottom-pr.y0)/4*1,
            pr.y0 + (grid_bottom-pr.y0)/4*2,
            pr.y0 + (grid_bottom-pr.y0)/4*3,
            grid_bottom]
    cols = [pr.x0,
            pr.x0 + pr.width/3*1,
            pr.x0 + pr.width/3*2,
            pr.x1]
    names_grid = [
        ["I","II","III"],
        ["aVR","aVL","aVF"],
        ["V1","V2","V3"],
        ["V4","V5","V6"]
    ]
    for r in range(4):
        for c in range(3):
            clip = fitz.Rect(cols[c], rows[r], cols[c+1], rows[r+1])
            name = names_grid[r][c]
            new_pdf = fitz.open()
            new_page = new_pdf.new_page(width=clip.width, height=clip.height)
            new_page.show_pdf_page(new_page.rect, src, 0, clip=clip)
            out_path = os.path.join(out_dir, f"{name}.pdf")
            new_pdf.save(out_path, clean=True, deflate=True)
            new_pdf.close()
            outputs.append((f"{name}.pdf", f"/segments/{os.path.basename(out_dir)}/{name}.pdf"))
    # rhythm II
    clip = fitz.Rect(pr.x0, grid_bottom, pr.x1, pr.y1)
    new_pdf = fitz.open()
    new_page = new_pdf.new_page(width=clip.width, height=clip.height)
    new_page.show_pdf_page(new_page.rect, src, 0, clip=clip)
    out_path = os.path.join(out_dir, "II_rhythm.pdf")
    new_pdf.save(out_path, clean=True, deflate=True)
    new_pdf.close()
    outputs.append(("II_rhythm.pdf", f"/segments/{os.path.basename(out_dir)}/II_rhythm.pdf"))

    src.close()
    logs.append(f"Fallback grid used. Segments generated: {len(outputs)}")
    return outputs

# ---------- Flask routes ----------
@app.route("/", methods=["GET","POST"])
def index():
    data = {"logs": ""}
    logs = []
    if request.method == "POST":
        f = request.files.get("pdf_file")
        if f and f.filename:
            filename = secure_filename(f.filename)
            in_path = os.path.join(UPLOAD_FOLDER, filename)
            f.save(in_path)
            base = os.path.splitext(filename)[0]

            # 1) Clean text (vector intact)
            cleaned_name = f"{base}_no_text.pdf"
            cleaned_path = os.path.join(OUTPUT_FOLDER, cleaned_name)
            logs.append(f"Cleaning text from: {filename}")
            remove_text_via_redaction(in_path, cleaned_path)
            data["cleaned_pdf_url"] = f"/outputs/{cleaned_name}"
            logs.append("Cleaned PDF saved.")

            # 2) Vector segmentation FROM CLEANED (so labels & any text are gone)
            seg_dir = os.path.join(SEGMENT_FOLDER, base)
            logs.append("Segmenting (vector, label-inferred grid preferred)...")
            try:
                # use labels from ORIGINAL to infer grid (more robust),
                # but clip from CLEANED to avoid any text inside segments
                label_src = fitz.open(in_path)
                page = label_src[0]
                label_words = _extract_label_words(page, logs)
                label_src.close()
                if len(label_words) >= 6:  # enough signal to infer grid
                    seg_urls = segment_vector_with_labels(cleaned_path, seg_dir, logs)
                else:
                    logs.append("Not enough labels; using fallback equal grid.")
                    seg_urls = segment_vector_fallback(cleaned_path, seg_dir, logs)
            except Exception as e:
                logs.append(f"Segmentation error: {e}\nUsing fallback grid.")
                seg_urls = segment_vector_fallback(cleaned_path, seg_dir, logs)

            data["segment_urls"] = seg_urls

    data["logs"] = "\n".join(logs)
    return render_template_string(HTML_TEMPLATE, data=data)

@app.route("/outputs/<path:filename>")
def dl_output(filename):
    return send_from_directory(OUTPUT_FOLDER, filename, as_attachment=True)

@app.route("/segments/<path:filename>")
def dl_segment(filename):
    return send_from_directory(SEGMENT_FOLDER, filename, as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
