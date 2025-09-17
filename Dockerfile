FROM python:3.13

WORKDIR /app

COPY src/n8n_metrics_exporter.py .
COPY src/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

ENV N8N_API_URL=http://localhost:5678
ENV N8N_API_KEY=""
ENV METRICS_PORT=9100
ENV N8N_API_SCRAPE_INTERVAL=15

EXPOSE ${METRICS_PORT}

CMD ["python", "n8n_metrics_exporter.py"]
