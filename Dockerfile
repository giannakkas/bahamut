FROM python:3.12

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

ENV PORT=8000
EXPOSE 8000

CMD sh -c "alembic upgrade head && uvicorn bahamut.main:app --host 0.0.0.0 --port $PORT --workers 2"
