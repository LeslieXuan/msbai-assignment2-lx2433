FROM python:3.11-slim

WORKDIR /app

# System deps kept minimal; wheels cover pandas/pyarrow/grpc.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Cloud Run injects PORT (default 8080). Streamlit must bind 0.0.0.0:$PORT.
ENV PORT=8080
EXPOSE 8080

CMD streamlit run app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
