FROM node:22-slim AS frontend-build

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY --from=frontend-build /frontend/dist ./frontend/dist

EXPOSE 8113

CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port 8113"]
