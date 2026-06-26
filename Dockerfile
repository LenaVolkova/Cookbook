# Use official lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY cookbook_frontend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app/ package (needed for agent spreadsheet functions)
COPY app/ ./app/

# Copy the service account key
COPY service-account.json .

# Copy the frontend files
COPY cookbook_frontend/main.py .
COPY cookbook_frontend/index.html .

# Set PYTHONPATH
ENV PYTHONPATH=/app

# Run the app. Cloud Run injects the PORT environment variable
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
