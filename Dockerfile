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

# Trust X-Forwarded-For / X-Forwarded-Proto only from private-network peers
# (the reverse proxy on the Docker network). Without this, every visitor
# looks like the proxy's IP -- sharing one rate-limit bucket -- and HTTPS
# requests look like plain HTTP, so session cookies never get `Secure`.
# Narrow it to your proxy's address in .env if you know it.
ENV FORWARDED_ALLOW_IPS="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port 8113"]
