#!/bin/bash
# Trailing Stop Manager Startup Script
# Ensures clean start by killing ALL related processes and ports

PID_FILE="/Users/kai/PycharmProjects/stock_bots/.pids"
cd "$(dirname "$0")"

echo "=== Trailing Stop Manager ==="
echo ""

# ============================================
# PHASE 1: Kill processes from PID file
# ============================================
if [ -f "$PID_FILE" ]; then
    echo "[1/5] Killing processes from PID file..."
    while read pid; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "  → Killing PID $pid"
            kill -9 "$pid" 2>/dev/null
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
else
    echo "[1/5] No PID file found"
fi

# ============================================
# PHASE 2: Kill all related processes by name
# ============================================
echo "[2/5] Killing all Reflex/Bun/Node processes..."

# Kill by process name patterns (aggressive)
for pattern in \
    "reflex run" \
    "reflex_app" \
    "trailing_stop_web" \
    "bun run dev" \
    "bun.*trailing" \
    "node.*next" \
    "node.*\.next"; do
    pids=$(pgrep -f "$pattern" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "  → Killing '$pattern': $pids"
        echo "$pids" | xargs kill -9 2>/dev/null
    fi
done

sleep 0.5

# ============================================
# PHASE 3: Free all potential ports
# ============================================
echo "[3/5] Freeing ports 3000-3010 and 8000-8010..."

for port in $(seq 3000 3010) $(seq 8000 8010); do
    pids=$(lsof -t -i :$port 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "  → Port $port: killing PIDs $pids"
        echo "$pids" | xargs kill -9 2>/dev/null
    fi
done

sleep 0.5

# ============================================
# PHASE 4: Verify clean state
# ============================================
echo "[4/5] Verifying clean state..."

# Check if any ports are still in use
still_used=""
for port in 3000 3001 3002 8000; do
    if lsof -i :$port 2>/dev/null | grep -q LISTEN; then
        still_used="$still_used $port"
    fi
done

if [ -n "$still_used" ]; then
    echo ""
    echo "ERROR: Ports still in use:$still_used"
    echo "Remaining processes:"
    lsof -i :3000 -i :3001 -i :3002 -i :8000 2>/dev/null | head -20
    echo ""
    echo "Try: sudo kill -9 \$(lsof -t -i :3000)"
    exit 1
fi

echo "  ✓ All ports free"
echo ""

# ============================================
# PHASE 5: Clear Vite cache (prevents module import errors)
# ============================================
echo "[5/5] Clearing Vite cache..."
if [ -d ".web/node_modules/.vite" ]; then
    rm -rf .web/node_modules/.vite
    echo "  ✓ Vite cache cleared"
else
    echo "  ✓ No Vite cache found"
fi

# ============================================
# START APP
# ============================================
echo "Starting Reflex app..."
echo ""

# Exclude data and logs from hot-reload to prevent TWS disconnect
export REFLEX_HOT_RELOAD_EXCLUDE_PATHS="data:logs"

# Start reflex in background
.venv/bin/reflex run &
REFLEX_PID=$!

# Wait for child processes to spawn
sleep 2

# Save all related PIDs for next shutdown
echo "$REFLEX_PID" > "$PID_FILE"
pgrep -f "reflex run" >> "$PID_FILE" 2>/dev/null
pgrep -f "bun run dev" >> "$PID_FILE" 2>/dev/null
pgrep -f "trailing_stop_web" >> "$PID_FILE" 2>/dev/null
pgrep -f "node.*next" >> "$PID_FILE" 2>/dev/null

# Remove duplicates from PID file
sort -u "$PID_FILE" -o "$PID_FILE"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  App started! PIDs saved to .pids"
echo "  Open: http://localhost:3000"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Open browser after short delay
(sleep 3 && open http://localhost:3000) &

# Wait for reflex process
wait $REFLEX_PID
