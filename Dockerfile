FROM python:3.14-slim

WORKDIR /app

# Install system dependencies for all Python packages
RUN apt-get update && apt-get install -y \
    # Git for vault sync
    git \
    \
    # Build tools (needed for scikit-image compilation)
    gcc \
    g++ \
    \
    # curl for healthcheck
    curl \
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

# Create non-root user for security
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

# Install uv (as root, into system path)
RUN pip install uv

# Hand off /app to appuser and switch early so all subsequent layers run as appuser
RUN chown appuser:appuser /app
USER appuser

# Copy dependency files and install (cached if uv.lock unchanged)
COPY --chown=appuser:appuser pyproject.toml uv.lock README.md ./

# Use cache mount for uv downloads - makes rebuilds fast even when pyproject.toml version changes
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen

# Copy application code
# NOTE: version.json should be generated before build with: ./scripts/generate-version.sh
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser config/ ./config/
COPY --chown=appuser:appuser templates/ ./templates/

# Copy startup scripts
COPY --chown=appuser:appuser scripts/ ./scripts/
RUN chmod +x /app/scripts/*.sh

# Create temp directory for uploads and logs
RUN mkdir -p /tmp/reserve_uploads /app/logs

# Expose port
EXPOSE 8000

# Healthcheck using correct endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Run via entrypoint script (handles git pull + backup scheduler)
CMD ["/app/scripts/entrypoint.sh"]
