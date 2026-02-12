FROM python:3.11-slim

# Create non-root user (required by HF Spaces)
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p logs && chown -R appuser:appuser /app

USER appuser

# Gradio config
ENV GRADIO_SERVER_NAME=0.0.0.0
ENV GRADIO_SERVER_PORT=7860

EXPOSE 7860

CMD ["python", "app.py"]
