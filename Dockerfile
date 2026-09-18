FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY simulator ./simulator
COPY configs ./configs
COPY tests ./tests

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -e ".[dev]"

CMD ["pytest", "-q"]
