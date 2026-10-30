FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ACCEPT_EULA=Y

WORKDIR /app

# Install system dependencies and Microsoft ODBC Driver 18

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    openssh-client \
    unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/config/debian/13/packages-microsoft-prod.deb \
    -o /tmp/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && rm /tmp/packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies

COPY requirements.txt .

# Install CPU-only PyTorch (avoids CUDA dependencies)

RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.13.0+cpu

# Install remaining Python dependencies

RUN pip install --no-cache-dir --timeout=300 --retries=10 -r requirements.txt

# Copy application files

COPY . .

# Make startup script executable

RUN chmod +x start.sh

# Start application

CMD ["./start.sh"]
