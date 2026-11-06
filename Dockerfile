# Pinned to a patch version and digest, so a rebuild uses the same base image.
FROM python:3.15.2-slim

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY pyproject.toml README.md config.yaml ./
COPY src ./src
COPY sample_data ./sample_data
COPY tests ./tests
RUN pip install --no-deps . && mkdir outputs && chown -R app:app /app

USER app
CMD ["ingest-project", "--config", "config.yaml", "--output", "outputs", "--check-date", "2026-04-01"]
