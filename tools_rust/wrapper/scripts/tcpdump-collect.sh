#!/bin/bash
set -euo pipefail
sudo tcpdump -i lo -s 0 -w mcp_debug.pcap tcp port 8080
