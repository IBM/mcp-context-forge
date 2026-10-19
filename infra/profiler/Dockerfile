FROM python:3.12-slim

# Pinned py-spy for gateway CPU profiling sidecars (make profile-gateway).
RUN pip install --no-cache-dir py-spy==0.4.2

ENTRYPOINT ["py-spy"]
