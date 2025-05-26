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

# Import Pydantic Settings singleton
from mcpgateway.config import settings

# import multiprocessing

# Bind to exactly what .env (or defaults) says
bind    = f"{settings.host}:{settings.port}"

workers = 8  # A positive integer generally in the 2-4 x $(NUM_CORES)
timeout = 600  # Set a timeout of 600
loglevel = "info"  # debug info warning error critical
max_requests = 10000  # The maximum number of requests a worker will process before restarting
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

# certfile = 'certs/cert.pem'
# keyfile  = 'certs/key.pem'
# ca-certs = '/etc/ca_bundle.crt'

# server hooks


def when_ready(server):
    server.log.info("Server is ready. Spawning workers")


def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)


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
