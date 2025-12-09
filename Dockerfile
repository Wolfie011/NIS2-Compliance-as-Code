FROM python:3.11-slim

WORKDIR /app

# Zmienne środowiskowe dla Pythona
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Zależności tylko serwera
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Kod serwera + reguły + binarka agenta
COPY nis2_server ./nis2_server
COPY rules ./rules
COPY downloads ./downloads

# Katalog na dane serwera
VOLUME ["/app/server_data"]

EXPOSE 8000

CMD ["uvicorn", "nis2_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
