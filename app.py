# app.py

import os
import subprocess
import glob
import json
import xml.etree.ElementTree as ET
import uuid
import shutil
import io
from flask import Flask, render_template, request, send_file
from svg.path import parse_path

app = Flask(__name__)
TEMP_DIR = "temp_files"

# დამხმარე ფუნქციები PDF-ის კონვერტაციისთვის და კოორდინატების ამოღებისთვის
def convert_pdf_to_svg(pdf_path, temp_request_dir):
    output_basename = os.path.splitext(os.path.basename(pdf_path))[0]
    output_prefix = os.path.join(temp_request_dir, output_basename)
    command = ['pdftocairo', '-svg', pdf_path, output_prefix]
    
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return glob.glob(f'{output_prefix}*.svg')
    except Exception as e:
        print(f"Error during PDF to SVG conversion: {e}")
        return []

def extract_coordinates_from_svg(svg_path):
    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
        namespace = '{http://www.w3.org/2000/svg}'
        all_paths = root.findall(f".//{namespace}path")
        
        if not all_paths: return None
        
        longest_path_element = max(all_paths, key=lambda p: len(p.get('d', '')))
        d_attribute = longest_path_element.get('d')
        path_data = parse_path(d_attribute)
        
        return [[seg.end.real, seg.end.imag] for seg in path_data]
    except Exception as e:
        print(f"Error during SVG coordinate extraction: {e}")
        return None

# მთავარი გვერდის მარშრუტი
@app.route('/')
def index():
    return render_template('index.html')

# ფაილის ატვირთვის და დამუშავების მარშრუტი
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'pdf_file' not in request.files:
        return "No file part", 400
    
    file = request.files['pdf_file']
    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return "Invalid file selected", 400

    # ვქმნით უნიკალურ დროებით საქაღალდეს თითოეული მოთხოვნისთვის
    request_id = str(uuid.uuid4())
    temp_request_dir = os.path.join(TEMP_DIR, request_id)
    os.makedirs(temp_request_dir, exist_ok=True)

    try:
        pdf_path = os.path.join(temp_request_dir, file.filename)
        file.save(pdf_path)

        # ეტაპი 1: PDF -> SVG
        svg_files = convert_pdf_to_svg(pdf_path, temp_request_dir)
        if not svg_files:
            return "Failed to convert PDF to SVG. Is Poppler installed correctly on the server?", 500

        # ვიღებთ მხოლოდ პირველი გვერდის SVG-ს
        svg_to_process = svg_files[0]
        
        # ეტაპი 2: SVG -> Coordinates
        coords = extract_coordinates_from_svg(svg_to_process)
        if not coords:
            return "Could not find ECG coordinates in the generated SVG.", 500
        
        # ვამზადებთ JSON მონაცემებს
        output_data = {
            "source_pdf": file.filename,
            "processed_svg": os.path.basename(svg_to_process),
            "point_count": len(coords),
            "coordinates": coords
        }

        # ვქმნით ფაილს მეხსიერებაში და ვაბრუნებთ გადმოსაწერად
        mem_file = io.BytesIO()
        mem_file.write(json.dumps(output_data, indent=4).encode('utf-8'))
        mem_file.seek(0)

        json_filename = f"{os.path.splitext(file.filename)[0]}_coords.json"
        
        return send_file(
            mem_file,
            as_attachment=True,
            download_name=json_filename,
            mimetype='application/json'
        )

    finally:
        # აუცილებლად ვშლით დროებით საქაღალდეს და მის შიგთავსს
        if os.path.exists(temp_request_dir):
            shutil.rmtree(temp_request_dir)

if __name__ == '__main__':
    # ვქმნით მთავარ დროებით საქაღალდეს, თუ არ არსებობს
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)
    # ლოკალურ კომპიუტერზე გასაშვებად
    app.run(host='0.0.0.0', port=5000, debug=True)
