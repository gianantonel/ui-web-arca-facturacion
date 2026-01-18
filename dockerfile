# Dockerfile
FROM python:3.11-slim

# Evita logs bufferizados y mejora comportamiento en contenedor
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias del sistema (mínimas; podés sacar curl si no lo usás)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copiamos requirements primero para aprovechar cache de Docker
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el código
COPY app.py utils.py ./

# Carpeta donde guardás JSON (tu app guarda en folder="data")
RUN mkdir -p /app/data

# Streamlit corre en 8501
EXPOSE 8501

# Comando para levantar Streamlit en contenedor
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
