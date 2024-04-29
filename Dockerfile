FROM python:3.9-slim-buster

# Set environment variables
ENV SONARR_URL='http://sonarr:8989'
ENV SONARR_API_KEY='123456'
ENV RADARR_URL='http://radarr:7878'
ENV RADARR_API_KEY='123456'
ENV API_TIMEOUT=600
ENV STALL_COUNT_LIMIT=3  # Default stall count limit
ENV RESET_STRIKES_ON_PROGRESS='1'  # Default reset strikes behavior

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code
COPY . .

# Define a volume where the strike data file will be stored
VOLUME ["/app/data"]

# Set the default command to execute when starting the container
CMD ["python", "cleaner.py"]
