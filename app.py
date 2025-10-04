# app.py-ში ჩასანაცვლებელი/გასაუმჯობესებელი ფუნქცია

def segment_vector_ecg_by_extraction(input_pdf, output_dir):
    """
    Splits the ECG into segments by extracting vector paths based on their color and position.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. პარამეტრები (შეიძლება დაგჭირდეთ დაკონფიგურირება)
    # ეკგ ხაზის ფერი (RGB, 0-1 შუალედში). თქვენს სურათზე ხაზი მუქია, სავარაუდოდ შავი.
    TARGET_COLOR = (0, 0, 0) 
    COLOR_TOLERANCE = 0.1 # ცდომილება ფერის ამოსაცნობად
    
    # განხრების სავარაუდო სახელები და რიგები
    LEAD_ROWS = [
        ["I", "aVR", "V1", "V4"],
        ["II", "aVL", "V2", "V5"],
        ["III", "aVF", "V3", "V6"]
    ]
    # რითმული ზოლის განხრა, რომელიც ხშირად ბოლოშია
    RHYTHM_STRIP_LEAD = "II" 

    doc = fitz.open(input_pdf)
    page = doc[0]
    
    # 2. ეკგ ხაზების ამოღება ფერის მიხედვით
    drawings = page.get_drawings()
    ecg_paths = []
    for path in drawings:
        if path["type"] == "s" and path["stroke_color"]:
            color = path["stroke_color"]
            if (abs(color[0] - TARGET_COLOR[0]) < COLOR_TOLERANCE and
                abs(color[1] - TARGET_COLOR[1]) < COLOR_TOLERANCE and
                abs(color[2] - TARGET_COLOR[2]) < COLOR_TOLERANCE):
                # დავიმახსოვროთ ხაზის გეომეტრია და მისი საშუალო ვერტიკალური პოზიცია
                y_coords = [p.y for item in path["items"] for p in item[1:]]
                if y_coords:
                    avg_y = sum(y_coords) / len(y_coords)
                    ecg_paths.append({"path": path, "avg_y": avg_y})

    if not ecg_paths:
        print("ეკგ ხაზები ვერ მოიძებნა ფერის მიხედვით.")
        return []

    # 3. ხაზების დაჯგუფება ვერტიკალური პოზიციის მიხედვით
    ecg_paths.sort(key=lambda p: p["avg_y"]) # დავალაგოთ Y კოორდინატით
    
    # ვიპოვოთ ვერტიკალური კლასტერები (რიგები)
    groups = []
    if ecg_paths:
        current_group = [ecg_paths[0]]
        for i in range(1, len(ecg_paths)):
            # თუ ორ ხაზს შორის ვერტიკალური დაშორება დიდია, ეს ახალი ჯგუფია
            if ecg_paths[i]["avg_y"] - ecg_paths[i-1]["avg_y"] > 20: # 20 პიქსელი - სატესტო ზღვარი
                groups.append(current_group)
                current_group = [ecg_paths[i]]
            else:
                current_group.append(ecg_paths[i])
        groups.append(current_group)

    # 4. თითოეული ჯგუფის (განხრის) შენახვა ცალკე PDF-ად
    segment_files = []
    lead_index = 0
    
    # TODO: აქ ლოგიკა შეიძლება დაიხვეწოს, რომ 4 სვეტად დალაგებული განხრებიც გაარჩიოს
    # ეს მაგალითი თითოეულ ვერტიკალურ ჯგუფს ერთ განხრად თვლის.
    
    leads = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]
    
    for i, group in enumerate(groups):
        if i >= len(leads): break
        
        lead_name = leads[i]
        
        # შევქმნათ ახალი PDF ამ კონკრეტული განხრისთვის
        new_pdf = fitz.open()
        # ვიპოვოთ ამ ჯგუფის საზღვრები, რომ გვერდის ზომა განვსაზღვროთ
        min_x = min(p.x for p_info in group for item in p_info["path"]["items"] for p in item[1:])
        max_x = max(p.x for p_info in group for item in p_info["path"]["items"] for p in item[1:])
        min_y = min(p.y for p_info in group for item in p_info["path"]["items"] for p in item[1:])
        max_y = max(p.y for p_info in group for item in p_info["path"]["items"] for p in item[1:])

        # დავამატოთ ცოტა სივრცე (padding)
        padding = 10
        width = (max_x - min_x) + 2 * padding
        height = (max_y - min_y) + 2 * padding
        
        new_page = new_pdf.new_page(width=width, height=height)
        
        # დავხატოთ ყველა სეგმენტი ამ ჯგუფიდან ახალ გვერდზე
        for path_info in group:
            for item in path_info["path"]["items"]:
                # კოორდინატების გადატანა ახალი გვერდის საწყის წერტილში
                if item[0] == "l": # Line
                    p1 = item[1] - fitz.Point(min_x - padding, min_y - padding)
                    p2 = item[2] - fitz.Point(min_x - padding, min_y - padding)
                    new_page.draw_line(p1, p2)
                elif item[0] == "c": # Bezier Curve
                    p1 = item[1] - fitz.Point(min_x - padding, min_y - padding)
                    p2 = item[2] - fitz.Point(min_x - padding, min_y - padding)
                    p3 = item[3] - fitz.Point(min_x - padding, min_y - padding)
                    p4 = item[4] - fitz.Point(min_x - padding, min_y - padding)
                    new_page.draw_bezier(p1, p2, p3, p4)

        seg_path = os.path.join(output_dir, f"{lead_name}.pdf")
        new_pdf.save(seg_path)
        new_pdf.close()
        segment_files.append(f"/{seg_path}")
        
    return segment_files


# --- app.py-ში @app.route("/") ფუნქციაში შეცვალეთ ეს ხაზი ---
# ძველი: segments = segment_vector_ecg(cleaned_pdf_path, segment_output_dir)
# ახალი:
# segments = segment_vector_ecg_by_extraction(cleaned_pdf_path, segment_output_dir)
