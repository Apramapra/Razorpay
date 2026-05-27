FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Check that we are on the correct Python (must be 3.11)
RUN python3 --version

# Install only the needed system packages
RUN apt-get update && apt-get install -y \
    xvfb \
    libxcomposite1 libxdamage1 libatk1.0-0 libasound2 \
    libdbus-1-3 libnspr4 libgbm1 libatk-bridge2.0-0 \
    libcups2 libxkbcommon0 libatspi2.0-0 libnss3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install (with exact wheel versions)
COPY requirements.txt .
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    gunicorn==23.0.0 \
    requests==2.32.3 \
    playwright==1.47.0 \
    pydantic==2.9.2 \
    pydantic-core==2.23.4 \
    python-dotenv==1.0.1

# Copy application files
COPY api.py checker_engine.py .

# Environment variables
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV DISPLAY=:99
ENV PORT=8000

EXPOSE 8000

# Start virtual display + gunicorn
CMD ["sh", "-c", "Xvfb :99 -screen 0 1024x768x16 & gunicorn api:app --workers 1 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 120"]
