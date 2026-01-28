#!/bin/bash
# Enable replication connections from any host in the Docker network
# This script runs on PostgreSQL first start via /docker-entrypoint-initdb.d/

set -e

echo "Configuring pg_hba.conf for replication..."

# Add replication entry to pg_hba.conf
# Allow replication connections from any host using scram-sha-256 authentication
echo "host replication all 0.0.0.0/0 scram-sha-256" >> "$PGDATA/pg_hba.conf"

echo "Replication access configured successfully."
