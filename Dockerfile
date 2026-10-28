# Python 3.12 rather than 3.13/3.14: google-genai trips the newer typing
# deprecations on import, and a deploy is the wrong place to discover that.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    LLM_PROVIDER=gemini \
    FEYNLY_SQLITE_PATH=/tmp/feynly.db

WORKDIR /app

COPY requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt

COPY src/ ./src/
COPY sample_notes.md ./

# Hugging Face Spaces runs the container as a non-root user; Render is happy
# either way. Creating it explicitly keeps both hosts working unchanged.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Both hosts inject the port to bind. Default matches local use.
ENV PORT=7860
EXPOSE 7860

# gunicorn, not the Flask dev server: grading holds a request open for tens of
# seconds, so workers need a generous timeout and there must be more than one.
CMD exec gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --threads 4 \
    --timeout 300 \
    --access-logfile - \
    src.webapp:app
