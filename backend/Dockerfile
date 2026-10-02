# Backend image: Django + DRF + Channels served over ASGI.
# Python 3.13 is used in containers (stable ecosystem support); see ADR 0001.
FROM python:3.13-slim

# - No .pyc files in the bind-mounted source tree.
# - Unbuffered output so logs appear immediately in `docker compose logs`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first: this layer is cached as long as requirements
# do not change, so code edits do not trigger a full reinstall.
ARG INSTALL_DEV=false
COPY requirements/ requirements/
RUN if [ "$INSTALL_DEV" = "true" ]; then \
        pip install -r requirements/dev.txt; \
    else \
        pip install -r requirements/prod.txt; \
    fi

COPY . .

# Run as an unprivileged user: a compromised Django process must not be root
# inside the container.
RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app

EXPOSE 8000

# Production entrypoint (ASGI, required for WebSockets). docker-compose.yml
# overrides it with `runserver` for development auto-reload.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
