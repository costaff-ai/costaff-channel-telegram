FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# GITHUB_TOKEN is a fine-grained PAT scoped to costaff-channel-chatbot only.
# Required while that SDK repo is private; remove this block + restore the
# git URL to requirements.txt when the SDK is made public.
ARG GITHUB_TOKEN
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir "git+https://${GITHUB_TOKEN}@github.com/costaff-ai/costaff-channel-chatbot.git@main"

COPY . .

# Set PYTHONPATH to include the /app directory
ENV PYTHONPATH=/app

CMD ["python", "src/bot/telegram_bot.py"]
