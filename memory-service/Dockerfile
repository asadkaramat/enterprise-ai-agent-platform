FROM python:3.12-slim
WORKDIR /app
RUN adduser --disabled-password --gecos '' appuser
COPY pyproject.toml .
RUN pip install --no-cache-dir . && \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
COPY app/ ./app/
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 8003
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8003/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
