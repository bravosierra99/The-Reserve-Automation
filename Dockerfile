FROM python:3.14-slim

WORKDIR /app

# Install system dependencies for all Python packages
RUN apt-get update && apt-get install -y \
    # Build tools (needed for scikit-image compilation)
    gcc \
    g++ \
    \
    # Tesseract OCR + language data
    tesseract-ocr \
    tesseract-ocr-eng \
    \
    # Poppler for PDF processing
    poppler-utils \
    \
    # OpenCV system dependencies (CRITICAL - required for cv2)
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libglib2.0-0 \
    libgl1 \
    \
    # Pillow image format support (CRITICAL - required for JPEG/WebP/TIFF)
    libjpeg-turbo-progs \
    libwebp7 \
    libopenjp2-7 \
    libtiff6 \
    libfreetype6 \
    \
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
