FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY proto_client ./proto_client

RUN pip install --no-cache-dir ".[mcp]"

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 app
USER app

ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Leave PROTO_API_KEY unset so each request
# must carry its own `Authorization: Bearer <PROTO_API_KEY>` (see CLAUDE.md).

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['PORT'] + '/health')" || exit 1

CMD ["sh", "-c", "python -m proto_client.mcp --transport http --host 0.0.0.0 --port ${PORT}"]
