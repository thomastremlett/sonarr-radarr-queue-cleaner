# Use Python 3.9 slim image based on Debian Buster
FROM python:3.9-slim-buster

# Environment variables for API URLs and keys
ENV SONARR_URL=
ENV SONARR_API_KEY=
ENV RADARR_URL=
ENV RADARR_API_KEY=
ENV LIDARR_URL=
ENV LIDARR_API_KEY=


# Environment variables for API operation timeouts and download monitoring settings
ENV API_TIMEOUT=600  
ENV GLOBAL_STALL_LIMIT='3'  
ENV SONARR_STALL_LIMIT='3'
ENV RADARR_STALL_LIMIT='3'
ENV LIDARR_STALL_LIMIT='3'
ENV RESET_STRIKES_ON_PROGRESS='1'  

# Environment variables to control auto-search functionality (default off)
ENV SONARR_AUTO_SEARCH='false'
ENV RADARR_AUTO_SEARCH='false'
ENV LIDARR_AUTO_SEARCH='false'

# Set the working directory inside the container
WORKDIR /app

# Copy the Python requirements file and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code to the container
COPY . .

# Define a Docker volume for persistent data storage
VOLUME ["/app/data"]

# Define the default command to run when starting the container
CMD ["python", "cleaner.py"]
