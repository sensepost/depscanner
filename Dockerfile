# Use Python 3.12 base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install envsubst (part of gettext)
RUN apt-get update && apt-get install -y gettext-base && rm -rf /var/lib/apt/lists/*

# Create the logs folder
RUN mkdir -p logs 
RUN mkdir -p web/logs
RUN mkdir -p web/uploads/{repositories,organizations,domains}

# Add the script to simplify invocation
COPY depscanner.sh /usr/local/bin/depscanner
RUN chmod +x /usr/local/bin/depscanner

# Copy requirements and script
COPY requirements.txt .
COPY . /app/
COPY config.yml .
COPY *.py ./

# Install dependencies
RUN chmod +x depscan.py
RUN pip install --no-cache-dir -r requirements.txt

