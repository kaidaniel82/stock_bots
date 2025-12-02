#!/bin/bash
# Trailing Stop Manager Startup Script
# Kills old processes and starts fresh

PID_FILE="/Users/kai/PycharmProjects/stock_bots/.pids"
cd "$(dirname "$0")"

echo "=== Trailing Stop Manager ==="

# Kill old processes from PID file
if [ -f "$PID_FILE" ]; then
    echo "Killing old processes from PID file..."
    while read pid; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "  Killing PID $pid"
            kill -9 "$pid" 2>/dev/null
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
fi

# Also kill any stray reflex/bun processes
echo "Cleaning up stray processes..."
pkill -9 -f "reflex run" 2>/dev/null
pkill -9 -f "bun run dev" 2>/dev/null
pkill -9 -f "trailing_stop_web" 2>/dev/null

# Wait for processes to die
sleep 0.5

# Force kill anything on ports 3000/8000
for port in 3000 8000; do
    pid=$(lsof -t -i :$port 2>/dev/null)
    if [ -n "$pid" ]; then
        echo "  Killing process on port $port (PID $pid)"
        kill -9 $pid 2>/dev/null
    fi
done

sleep 0.3

# Verify ports are free
if lsof -i :3000 -i :8000 2>/dev/null | grep -q LISTEN; then
    echo "ERROR: Ports 3000/8000 still in use!"
    lsof -i :3000 -i :8000 2>/dev/null
    exit 1
fi

echo "Starting Reflex app..."

# Start reflex in background and capture PIDs
.venv/bin/reflex run &
REFLEX_PID=$!

# Wait a moment for child processes to spawn
sleep 1

# Save all related PIDs
echo "$REFLEX_PID" > "$PID_FILE"
pgrep -f "reflex run" >> "$PID_FILE" 2>/dev/null
pgrep -f "bun run dev" >> "$PID_FILE" 2>/dev/null

echo ""
echo "App started! PIDs saved to $PID_FILE"
echo "Open: http://localhost:3000"
echo ""

# Open browser after short delay
(sleep 2 && open http://localhost:3000) &

# Wait for reflex process
wait $REFLEX_PID
