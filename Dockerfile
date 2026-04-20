FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir

COPY . .

ENTRYPOINT ["/bin/sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port $PORT"]
