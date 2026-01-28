# Export VENV_DIR environment variable for virtual environment path

export VENV_DIR="$HOME/.venv/mcpgateway"

# Automatically activate the virtual environment if it exists
if [ -f "$VENV_DIR/bin/activate" ]; then
  source "$VENV_DIR/bin/activate"
fi
