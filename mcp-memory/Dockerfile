FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml /app/
COPY src /app/src

RUN python -m pip install --no-cache-dir -e .

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "mcp_memory.main", "--host", "0.0.0.0", "--port", "8080", "--serve"]
