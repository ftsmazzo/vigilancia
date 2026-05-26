# Contexto de build: raiz do repositório (Build Path "/" no EasyPanel).
FROM python:3.12-slim

WORKDIR /app

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Inclui app/data/dicionariotudo.csv (dicionário CADU do assistente)
COPY apps/api/ .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
