FROM python:3.11-slim

# Set a working directory
WORKDIR /app

# Copy only the Python requirements first to leverage Docker layer caching
COPY bingx_bot/requirements.txt /app/bingx_bot/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /app/bingx_bot/requirements.txt

# Copy the application code into the container
COPY . /app

# Expose the Flask default port
EXPOSE 5000

# Use unbuffered output to improve logging in Docker
ENV PYTHONUNBUFFERED=1

# Default command: run the Flask web UI. The host/port can be overridden via
# docker-compose or command line arguments.
CMD ["python", "-m", "bingx_bot.ui.app", "--host", "0.0.0.0", "--port", "5000"]