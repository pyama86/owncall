FROM python:3.13-slim AS builder

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir --prefix=/install .


FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /install /usr/local

# Non-root user for security
RUN adduser --disabled-password --gecos "" owncall
USER owncall

ENTRYPOINT ["owncall"]
CMD ["-c", "/app/config.yml"]
