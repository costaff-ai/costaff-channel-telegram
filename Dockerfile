FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# PYTHONPATH=/app/src so `bot` resolves as a package — mirrors
# pytest.ini's `pythonpath = src` so tests + container behave the same.
ENV PYTHONPATH=/app/src

CMD ["python", "-m", "bot.telegram_bot"]
