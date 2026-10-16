FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt
COPY . .
RUN useradd --create-home --uid 10001 demo && mkdir -p /app/data /app/logs && chown -R demo:demo /app
USER demo
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
