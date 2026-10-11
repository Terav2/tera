# Tera — container image. Works on Railway, Fly.io, Cloud Run, any Docker host.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persist the knowledge base outside the image.
ENV TERA_DB=/data/tera_knowledge
VOLUME ["/data"]

ENV PORT=8080
EXPOSE 8080

CMD gunicorn -w 1 -k gthread --threads 4 -b 0.0.0.0:$PORT wsgi:app
