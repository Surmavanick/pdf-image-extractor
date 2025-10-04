# ვიყენებთ Python-ის ოფიციალურ, მცირე ზომის ვერსიას
FROM python:3.10-slim

# ვუთითებთ სამუშაო საქაღალდეს კონტეინერის შიგნით
WORKDIR /app

# ვანახლებთ პაკეტების სიას და ვაყენებთ poppler-utils-ს.
# ეს არის კრიტიკული ნაბიჯი PDF-ის კონვერტაციისთვის.
RUN apt-get update && \
    apt-get install -y poppler-utils && \
    rm -rf /var/lib/apt/lists/*

# ვაკოპირებთ დამოკიდებულებების ფაილს და ვაყენებთ მათ
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ვაკოპირებთ პროექტის დანარჩენ ფაილებს
COPY . .

# Render-ი დინამიურად გვაწვდის PORT ცვლადს. Gunicorn-ი ამ პორტზე გაეშვება.
# EXPOSE ეუბნება Docker-ს, რომ კონტეინერი ამ პორტს უსმენს.
EXPOSE 10000

# ბრძანება, რომელიც გაუშვებს აპლიკაციას Render-ზე
# Gunicorn-ი უშვებს app ობიექტს app.py ფაილიდან
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:10000", "app:app"]
