FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock README.md ./

# Install Python dependencies
RUN uv sync --frozen

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY templates/ ./templates/

# Create temp directory for uploads
RUN mkdir -p /tmp/reserve_uploads

# Expose port
EXPOSE 8000

# Run web application
CMD ["uv", "run", "uvicorn", "reserve_automation.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
