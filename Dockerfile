FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY proto_client ./proto_client

RUN pip install --no-cache-dir ".[mcp]"

ENV PORT=8080
ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "python -m proto_client.mcp --transport http --host 0.0.0.0 --port ${PORT}"]
