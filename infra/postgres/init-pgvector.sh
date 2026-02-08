#!/bin/bash
# Initialize pgvector extension for vector similarity search
# This script runs on PostgreSQL first start via /docker-entrypoint-initdb.d/

set -e

echo "Creating pgvector extension..."

# Create the extension in the default database
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
    
    -- Verify extension was created successfully
    SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
EOSQL

echo "pgvector extension created successfully."