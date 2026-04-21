FROM python:3.12

ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
RUN find . -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
RUN find . -name '*.pyc' -delete 2>/dev/null || true

ENV PORT=8000
EXPOSE 8000

CMD sh -c "alembic upgrade head && uvicorn bahamut.main:app --host 0.0.0.0 --port $PORT --workers 2"
