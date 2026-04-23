FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    curl \
    ca-certificates \
    gnupg \
    build-essential \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3.11-distutils \
    python3-pip \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python3.11 -m pip install --upgrade pip && python3.11 -m pip install -r /app/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend
COPY data /app/data

EXPOSE 8000

CMD ["python3.11", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
