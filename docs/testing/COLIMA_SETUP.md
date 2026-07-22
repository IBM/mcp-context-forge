# Colima Setup for Integration Tests

## Problem

Docker daemon not running because Colima (the Docker runtime on macOS) is stopped.

## Quick Fix

```bash
# Start Colima (this will start the Docker daemon)
colima start

# Verify Docker is working
docker ps

# Now run the integration tests
make vault-test-start
make test-vault-integration
```

## First-Time Colima Setup (if needed)

If Colima was never configured:

```bash
# Start with default settings (2 CPU, 2GB RAM)
colima start

# Or start with custom resources
colima start --cpu 4 --memory 4
```

## Troubleshooting

### Issue: "colima is not running"
```bash
colima start
```

### Issue: Docker commands fail after Colima starts
```bash
# Restart Colima
colima stop
colima start
```

### Issue: Slow performance
```bash
# Stop and restart with more resources
colima stop
colima start --cpu 4 --memory 8
```

## Colima Management

```bash
# Check status
colima status

# Stop Colima (frees resources)
colima stop

# Restart Colima
colima restart

# Delete Colima VM (complete reset)
colima delete
```

## Auto-Start on Login (Optional)

To avoid manually starting Colima each time:

1. **macOS System Settings** → **General** → **Login Items**
2. Click **+** button
3. Add: `/opt/homebrew/bin/colima`
4. Or use `launchd` (advanced):

```bash
# Create launch agent
cat > ~/Library/LaunchAgents/com.colima.autostart.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.colima.autostart</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/colima</string>
        <string>start</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

# Load the agent
launchctl load ~/Library/LaunchAgents/com.colima.autostart.plist
```

## Why Colima?

On macOS, Docker Desktop requires a license for commercial use. Colima is a free, open-source alternative that:

- Uses the same Docker CLI
- Compatible with docker-compose
- Lighter resource usage
- No licensing concerns

## Resources

- Colima GitHub: https://github.com/abiosoft/colima
- Docker CLI Docs: https://docs.docker.com/engine/reference/commandline/cli/

---

**Next Steps After Starting Colima:**

```bash
# 1. Start Colima
colima start

# 2. Verify Docker works
docker ps

# 3. Remove obsolete version warning from docker-compose.yml
# (This is cosmetic - the file works fine as-is)

# 4. Run integration tests
make vault-test-start
make test-vault-integration
```
