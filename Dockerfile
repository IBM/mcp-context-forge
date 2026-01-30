FROM python:3.11-slim

WORKDIR /app

# Copy entire project
COPY . .

# Install pip if needed
RUN python -m pip install --upgrade pip

# Install project with test dependencies
RUN pip install -e ".[test]"

# Default command: run unit tests
CMD ["pytest", "tests/unit/", "-v"]
