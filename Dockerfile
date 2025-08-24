# Pin a small Python base
FROM python:3.12-slim

# Avoid Python buffering (better logs)
ENV PYTHONUNBUFFERED=1

# Workdir
WORKDIR /app

# System deps (mostly for building wheels); keep tiny
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

# Copy code
COPY main.py /app/

# Install deps
RUN pip install --upgrade pip && \
    pip install discord.py python-dotenv

# Default command (matches fly.toml process below)
CMD ["python", "main.py"]
