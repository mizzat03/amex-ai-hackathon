FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY backend ./backend
COPY simulator ./simulator
COPY runbooks ./runbooks
RUN python -m pip install --upgrade pip && python -m pip install .

EXPOSE 8000 8010 8020
CMD ["python", "-m", "uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
