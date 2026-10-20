FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN python manage.py collectstatic --noinput && \
    mkdir -p /app/media && \
    chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py createcachetable && python manage.py seed_communities && gunicorn pans_agora.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile -"]
