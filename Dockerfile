FROM python:3.13-slim

WORKDIR /app

# Use stable Debian repos (avoid snapshot rotation issues during builds).
RUN echo "deb http://deb.debian.org/debian bookworm main" > /etc/apt/sources.list && \
    echo "deb http://deb.debian.org/debian bookworm-updates main" >> /etc/apt/sources.list && \
    echo "deb http://security.debian.org/debian-security bookworm-security main" >> /etc/apt/sources.list

# Multiple PostgreSQL client versions from pgdg so we can match server version
# at backup/restore time (avoids "unsupported version 1.16" mismatches).
# docker-ce-cli + docker-compose-plugin power the `restore` mode which can
# bring up services from a restored compose file + attach to their networks.
# mariadb-client covers both MySQL 5.7+/8.x and MariaDB 10.x/11.x.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] \
        https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
        https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client-15 \
        postgresql-client-16 \
        postgresql-client-17 \
        postgresql-client-18 \
        mariadb-client \
        sqlite3 \
        gzip \
        tar \
        docker-ce-cli \
        docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/logs /var/backups && chmod 0777 /app/logs /var/backups

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV UGB_CONFIG=/app/config.yaml

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["daemon"]
