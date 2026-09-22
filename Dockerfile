FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends procps smartmontools docker.io docker-compose && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app /app/app
RUN mkdir -p /app/config
EXPOSE 8088
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8088"]

RUN apt-get update && \
    apt-get install -y --no-install-recommends util-linux && \
    rm -rf /var/lib/apt/lists/*

COPY omv-bridge /opt/kyber-installer/omv-bridge
