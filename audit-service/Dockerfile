FROM python:3.12-slim
WORKDIR /app
RUN adduser --disabled-password --gecos '' appuser
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY app/ ./app/
USER appuser
EXPOSE 8004
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8004/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
