FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Don't run as root
RUN adduser --disabled-password --gecos '' appuser
RUN mkdir -p /app/data && chown appuser:appuser /app/data
USER appuser

# Default env
ENV HOST=0.0.0.0
ENV PORT=8000
ENV DATABASE_URL=sqlite:////app/data/bahamut.db

EXPOSE 8000

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
