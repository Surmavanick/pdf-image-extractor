# --- Base image ---
FROM python:3.11-slim

# --- Install system dependencies (Poppler for pdftocairo) ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    rm -rf /var/lib/apt/lists/*

# --- Set work directory ---
WORKDIR /app

# --- Copy project files into the container ---
COPY . /app

# --- Create temp directory for runtime ---
RUN mkdir -p temp_files

# --- Install Python dependencies ---
RUN pip install --no-cache-dir -r requirements.txt

# --- Expose port for Render ---
EXPOSE 5000

# --- Environment variables ---
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

# --- Start Gunicorn server ---
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--timeout", "120"]
