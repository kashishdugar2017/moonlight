# Moonlight in a box: the page and the API, ready for Google Cloud Run.
#
# No key lives in this file or in the image. The Gemini key is handed to
# the running container as the environment variable GEMINI_API_KEY.

FROM python:3.13-slim

# PORT: Cloud Run sets this itself. 8080 is used when nobody sets it.
# MOONLIGHT_CACHE_DIR: the cache notebook goes under /tmp, which the app
# is allowed to write.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    MOONLIGHT_CACHE_DIR=/tmp/moonlight-cache

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY moonlight/ moonlight/
COPY web/ web/

# Run as an ordinary user, not root.
RUN useradd --no-create-home --uid 10001 moonlight
USER moonlight

EXPOSE 8080

# "exec" lets uvicorn hear Cloud Run's stop signal and shut down cleanly.
CMD ["sh", "-c", "exec uvicorn moonlight.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
