FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic
RUN pip install --no-cache-dir .
RUN mkdir -p /data/storage
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
