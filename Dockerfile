FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY boardroom ./boardroom
ENV HOST=0.0.0.0 PORT=8000 BOARDROOM_DB_PATH=/data/boardroom.db
VOLUME ["/data"]
EXPOSE 8000
CMD ["python", "-m", "boardroom", "serve"]
