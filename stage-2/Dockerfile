FROM python:3.12-slim
WORKDIR /app
COPY core.py server.py stage.py requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
ENV POCKETFUL_STAGE=2
ENV POCKETFUL_DB=/tmp/pocketful/state.db
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["sh","-c","uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]
