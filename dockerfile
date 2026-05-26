# Use Playwright image with Python 3.11 (pre-built wheels available)
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Install system dependencies for headless Chrome & Rust (just in case)
RUN apt-get update && apt-get install -y \
    xvfb \
    libxcomposite1 \
    libxdamage1 \
    libatk1.0-0 \
    libasound2 \
    libdbus-1-3 \
    libnspr4 \
    libgbm1 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libnss3 \
    curl \
    build-essential \
    && curl https://sh.rustup.rs -sSf | sh -s -- -y \
    && rm -rf /var/lib/apt/lists/*

# Add Rust to PATH
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY api.py .
COPY checker_engine.py .

# Environment variables
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV DISPLAY=:99
ENV PORT=8000

EXPOSE 8000

# Start virtual display and gunicorn
CMD sh -c "Xvfb :99 -screen 0 1024x768x16 & gunicorn api:app --workers 1 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 120"
