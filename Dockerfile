# Use Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set Python unbuffered mode
ENV PYTHONUNBUFFERED=1

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the server code and client credentials
COPY hydrus_server.py .
COPY functions.py .
COPY hydrus_clients.json /run/secrets/HYDRUS_CLIENTS

# Create non-root user and set permissions
RUN useradd -m -u 1000 mcpuser
RUN chown -R mcpuser:mcpuser /app

# Switch to non-root user
USER mcpuser

# Network configuration
# use host network to access Hydrus API service
# This allows the container to access services running on the host machine

# Run the server with host network mode
CMD ["python", "hydrus_server.py"]