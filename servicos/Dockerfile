FROM python:3.12-slim
WORKDIR /servicos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH=/servicos PYTHONUNBUFFERED=1
