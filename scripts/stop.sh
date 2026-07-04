#!/bin/bash
# 停本地 dev
for f in /tmp/testmate-backend.pid /tmp/testmate-frontend.pid; do
  if [ -f "$f" ]; then
    pid=$(cat "$f")
    kill "$pid" 2>/dev/null && echo "stopped $pid"
    rm -f "$f"
  fi
done
