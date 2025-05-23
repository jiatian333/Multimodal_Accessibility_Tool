# Use the Python 3 official image
# https://hub.docker.com/_/python
FROM python:3

# Run in unbuffered mode
ENV PYTHONUNBUFFERED=1

# Create and change to the app directory.
WORKDIR /backend/main

# Copy local code to the container image.
COPY . ./

# Install project dependencies
RUN pip install --no-cache-dir -r backend/requirements.txt

# Run the web service on container startup.
CMD ["uvicorn", "backend.main:app --reload"]