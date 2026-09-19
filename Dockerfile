FROM python:3.11-slim

# Colophon is standard library only, so there is nothing to install.
WORKDIR /app
COPY colophon/ /app/colophon/

# Never write .pyc files: the root filesystem is read-only in normal use.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# A sensible non-root default. Docker compose should still set
# user: "PUID:PGID" so books come out owned by your library user.
USER 1000:1000

# No EXPOSE and no listening socket: Colophon only ever reads and writes files.
ENTRYPOINT ["python", "-m", "colophon"]
