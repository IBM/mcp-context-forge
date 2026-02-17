FROM pgvector/pgvector:pg18

# Copy initialization scripts
COPY init-replication.sh /docker-entrypoint-initdb.d/01-init-replication.sh
COPY init-pgvector.sh /docker-entrypoint-initdb.d/02-init-pgvector.sh

RUN chmod +x /docker-entrypoint-initdb.d/*.sh

EXPOSE 5432

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD pg_isready -U ${POSTGRES_USER:-postgres} || exit 1