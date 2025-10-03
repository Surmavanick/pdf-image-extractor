
# PDF Extractor (text + images)

Simple Flask app to extract **copyable text** and **original images** from a PDF.
Uploads the PDF, then saves extracted text as `.txt` and images as `.png` files.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

## Deploy to Render.com

- Create a new **Web Service**
- Connect to your GitHub repo
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
- Ensure disk or persistent storage if you need outputs to persist across restarts.

## Notes

- Images are exported as PNG. CMYK images are converted to RGB.
- Text is extracted with `PyMuPDF` (`page.get_text("text")`).
- Outputs are downloadable from `/outputs/...` URLs.
