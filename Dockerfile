FROM python:3.11-slim

# 1) OS deps for Playwright Chromium (important)
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    libu2f-udev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2) Install python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 3) Install Playwright browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m playwright install chromium

# 4) Copy app
COPY . /app

# 5) Run server (adjust module:app to match your project)
ENV PORT=10000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "10000"]
