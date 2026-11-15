# Use Python 3.11 slim image
FROM python:3.11-slim-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies including Playwright browser deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    # Playwright Chromium dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and Chromium browser
# playwright itself is pinned in requirements.txt; only the browser is installed here.
RUN playwright install chromium

# Copy application code
COPY backend/ .

# Create uploads directory
RUN mkdir -p uploads

# Expose port (Railway uses dynamic $PORT)
EXPOSE 8000

# Create tables from models, seed DB (roles + optional admin), run any pending
# Alembic migrations (idempotent — baseline skips CREATE TABLE if tables exist),
# then start the application.
# `exec` makes uvicorn PID 1 so Docker's SIGTERM reaches it. Without it sh is PID 1, swallows the
# signal, the shutdown hook never runs and Docker SIGKILLs mid-job after 10s. Open requests get 10s
# to finish, then the shutdown hook gives running scheduler jobs up to 25s (stop_grace_period: 40s).
CMD python init_db.py && alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 300 --timeout-graceful-shutdown 10
