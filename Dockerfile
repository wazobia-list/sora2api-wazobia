FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# --- Playwright deps for Debian (avoid Playwright's Ubuntu deps installer) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    fonts-ubuntu fonts-unifont \
    libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libgbm1 \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libxkbcommon0 \
    libpango-1.0-0 libcairo2 \
    libasound2 \
    libglib2.0-0 \
    libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN mkdir -p /ms-playwright && chmod -R 777 /ms-playwright

# install the browser only (no OS deps)
RUN python -m playwright install chromium

COPY . .

# Render provides PORT
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
