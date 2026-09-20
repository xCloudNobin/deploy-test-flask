import multiprocessing
import os

# Health checks share a small worker pool; nproc guard keeps the footprint
# modest on small hosts.
_cpu = int(multiprocessing.cpu_count() or 1)
workers = min(int(os.environ.get("WEB_CONCURRENCY", "2")), _cpu)
threads = int(os.environ.get("WEB_THREADS", "4"))

# Load the app once in the master before forking so the session signing key
# (SECRET_KEY) is identical across workers. For true multi-instance scaling,
# pin SECRET_KEY via the environment (see .env.example).
preload_app = True

# Bind to all interfaces with the platform-configurable port.
host = os.environ.get("HOST", "0.0.0.0")
port = os.environ.get("PORT", "8000")
bind = f"{host}:{port}"

# Sanitized request logging on stdout; errors on stderr.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

graceful_timeout = 15
timeout = 30
