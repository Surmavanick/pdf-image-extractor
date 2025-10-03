# syntax=docker/dockerfile:1
FROM python:3.11-slim

# System deps (fitz/PyMuPDF works fine with slim + basic build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    libopenjp2-7 \
    libxcb1 \ 
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Expose port for Render/containers
ENV PORT=5000
EXPOSE 5000

# Use gunicorn in Docker
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000"]
