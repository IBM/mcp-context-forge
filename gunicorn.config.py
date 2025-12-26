# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Description: GUNICORN CONFIGURATION
Reference: https://docs.gunicorn.org/en/stable/settings.html
Notes:
- Set bind = "0.0.0.0:4444" to set the IP (all) and port (4444)
- Set a timeout to avoid worker timeout in containers, as the workers
will have to wait a long time for queries
Reference: https://stackoverflow.com/questions/10855197/frequent-worker-timeout
"""

# Standard
import os

# First-Party
# Import Pydantic Settings singleton
from mcpgateway.config import settings

# import multiprocessing

# Bind to exactly what .env (or defaults) says
bind = f"{settings.host}:{settings.port}"

workers = 2  # A positive integer generally in the 2-4 x $(NUM_CORES)
timeout = 600  # Set a timeout of 600
loglevel = "info"  # debug info warning error critical
max_requests = 100000  # The maximum number of requests a worker will process before restarting
max_requests_jitter = 100  # The maximum jitter to add to the max_requests setting.

# Optimization https://docs.gunicorn.org/en/stable/settings.html#preload-app
preload_app = True  # Load application code before the worker processes are forked.
reuse_port = True  # Set the SO_REUSEPORT flag on the listening socket


# Server model: https://docs.gunicorn.org/en/stable/design.html
# worker-class = "eventlet" #  Requires eventlet >= 0.24.1, pip install gunicorn[eventlet]
# worker-class = "gevent"   #  Requires gevent >= 1.4, pip install gunicorn[gevent]
# worker_class = "tornado"  #  Requires tornado >= 0.2, pip install gunicorn[tornado]
# threads = 2       # A positive integer generally in the 2-4 x $(NUM_CORES) range.
# gevent

# pidfile = '/tmp/gunicorn-pidfile'
# errorlog = '/tmp/gunicorn-errorlog'
# accesslog = '/tmp/gunicorn-accesslog'
# access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# SSL/TLS Configuration
# Note: certfile and keyfile are set via command-line arguments in run-gunicorn.sh
# If a passphrase is provided via SSL_KEY_PASSWORD environment variable,
# the key will be decrypted by the SSL key manager before Gunicorn starts.
# certfile = 'certs/cert.pem'
# keyfile  = 'certs/key.pem'
# ca-certs = '/etc/ca_bundle.crt'

# Global variable to store the prepared key file path
_prepared_key_file = None

# server hooks


def on_starting(server):
    """Called just before the master process is initialized.

    This is where we handle passphrase-protected SSL keys by decrypting
    them to a temporary file before Gunicorn workers start.
    """
    global _prepared_key_file

    # Check if SSL is enabled via environment variable (set by run-gunicorn.sh)
    # and a passphrase is provided
    ssl_enabled = os.environ.get("SSL", "false").lower() == "true"
    ssl_key_password = os.environ.get("SSL_KEY_PASSWORD")

    if ssl_enabled and ssl_key_password:
        try:
            from mcpgateway.utils.ssl_key_manager import prepare_ssl_key

            # Get the key file path from environment (set by run-gunicorn.sh)
            key_file = os.environ.get("KEY_FILE", "certs/key.pem")

            server.log.info(f"Preparing passphrase-protected SSL key: {key_file}")

            # Decrypt the key and get the temporary file path
            _prepared_key_file = prepare_ssl_key(key_file, ssl_key_password)

            server.log.info(f"SSL key prepared successfully: {_prepared_key_file}")

            # Update the keyfile setting to use the decrypted temporary file
            # This is a bit of a hack, but Gunicorn doesn't provide a better way
            # to modify the keyfile after it's been set via command line
            if hasattr(server, 'cfg'):
                server.cfg.set('keyfile', _prepared_key_file)

        except Exception as e:
            server.log.error(f"Failed to prepare SSL key: {e}")
            raise


def when_ready(server):
    server.log.info("Server is ready. Spawning workers")


def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)
    # Reset Redis client state so each worker creates its own connection
    # This is necessary because --preload causes the client to be initialized
    # in the master process, but each forked worker needs its own event loop
    try:
        from mcpgateway.utils.redis_client import _reset_client
        _reset_client()
    except ImportError:
        pass


def post_worker_init(worker):
    worker.log.info("worker initialization completed")


def worker_int(worker):
    worker.log.info("worker received INT or QUIT signal")


def worker_abort(worker):
    worker.log.info("worker received SIGABRT signal")


def worker_exit(server, worker):
    server.log.info("Worker exit (pid: %s)", worker.pid)


def child_exit(server, worker):
    server.log.info("Worker child exit (pid: %s)", worker.pid)
