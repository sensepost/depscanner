#!/bin/bash

echo "Launching the web for depscanner"

# Ensure the logs directory exists
if [ ! -d "web/logs" ]; then
  mkdir -p web/logs
  echo "Created web/logs directory"
fi

# Navigate to the web directory and start Flask
cd web && flask run --port 8015