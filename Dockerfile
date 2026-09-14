# ClauseGuard — AWS Bedrock AgentCore Runtime Container
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (build tools, libmagic, poppler for pdf)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    AGENTCORE_PORT=8080 \
    AWS_DEFAULT_REGION=us-east-1

# Expose standard SageMaker / AgentCore runtime port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/ping || exit 1

# Start AgentCore Runtime server
CMD ["python", "agentcore_runtime.py"]
