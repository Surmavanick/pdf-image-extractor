# app.py
import io, json, re
from flask import Flask, render_template, request, send_file
import fitz  # PyMuPDF
import xml.etree.ElementTree as ET
from svg.path import parse_path

app = Flask(__name__)

def _sample_path_coords(d_attr: str, samples_per_seg: int = 50, max_points: int = 50000):
    """Sample coordinates along an SVG path 'd' attribute."""
    try:
        path = parse_path(d_attr)
    except Exception:
        return []

    coords = []
    for seg in path:
        n = max(2, samples_per_seg)
        for i in range(n):
            t = i / (n - 1)
            pt = seg.point(t)
            coords.append([float(pt.real), float(pt.imag)])
            if len(coords) >= max_points:
                return coords
    return coords

def _poly_points_to_coords(points_attr: str):
    """Convert 'points' attribute of <polyline>/<polygon> to list of [x,y]."""
    nums = [float(x) for x in re.split(r"[,\s]+", points_attr.strip()) if x]
    return [[nums[i], nums[i+1]] for i in range(0, len(nums) - 1, 2)]

def extract_coords_from_svg_text(svg_text: str, samples_per_seg: int = 50):
    """Parse SVG string and return combined coordinates + breakdown by element."""
    root = ET.fromstring(svg_text)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    paths = root.findall(".//svg:path", ns)
    polylines = root.findall(".//svg:polyline", ns)
    lines = root.findall(".//svg:line", ns)

    by_element = []

    # <path>
    for p in paths:
        d = p.get("d")
        if not d:
            continue
        pts = _sample_path_coords(d, samples_per_seg=samples_per_seg)
        if pts:
            by_element.append({"type": "path", "count": len(pts), "coords": pts})

    # <polyline>
    for pl in polylines:
        pts_attr = pl.get("points")
        if not pts_attr:
            continue
        pts = _poly_points_to_coords(pts_attr)
        if pts:
            by_element.append({"type": "polyline", "count": len(pts), "coords": pts})

    # <line>
    for ln in lines:
        try:
            x1 = float(ln.get("x1", "0")); y1 = float(ln.get("y1", "0"))
            x2 = float(ln.get("x2", "0")); y2 = float(ln.get("y2", "0"))
            by_element.append({"type": "line", "count": 2, "coords": [[x1, y1], [x2, y2]]})
        except Exception:
            continue

    # flatten
    flat = []
    for item in by_element:
        flat.extend(item["coords"])

    return {
        "num_elements": len(by_element),
        "elements": by_element,       # detail per element
        "total_points": len(flat),
        "coordinates": flat           # flattened coordinates (backward compatible)
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    if "pdf_file" not in request.files:
        return "No file part", 400
    f = request.files["pdf_file"]
    if not f.filename.lower().endswith(".pdf"):
        return "Invalid file selected", 400

    # Read PDF bytes in-memory (no temp files, works great on Render)
    pdf_bytes = f.read()

    # Open with PyMuPDF and export first page to SVG (no Poppler needed)
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.page_count == 0:
            return "Empty PDF", 400
        page = doc[0]  # first page; extend to loop pages if you like
        svg_text = page.get_svg_image()  # SVG markup as string
    except Exception as e:
        return f"Failed to read PDF: {e}", 500
    finally:
        try:
            doc.close()
        except Exception:
            pass

    # Parse SVG and extract ECG-like vectors
    try:
        result = extract_coords_from_svg_text(svg_text, samples_per_seg=50)
    except Exception as e:
        return f"Failed to parse SVG: {e}", 500

    output = {
        "source_pdf": f.filename,
        "method": "pymupdf_get_svg_image",
        "page": 1,
        "num_elements": result["num_elements"],
        "point_count": result["total_points"],
        "coordinates": result["coordinates"],  # flattened for compatibility
        "elements": result["elements"]         # detailed breakdown
    }

    mem = io.BytesIO()
    mem.write(json.dumps(output, ensure_ascii=False, indent=2).encode("utf-8"))
    mem.seek(0)
    json_name = f"{f.filename.rsplit('.',1)[0]}_coords.json"

    return send_file(mem, as_attachment=True, download_name=json_name, mimetype="application/json")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
