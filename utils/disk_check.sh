#!/usr/bin/env bash
# ============================================================================
# FILE: utils/disk_check.sh
# PURPOSE: Quick disk pressure check for this server, with Docker breakdown.
# USAGE: bash utils/disk_check.sh
#        watch -n 30 bash utils/disk_check.sh
# ============================================================================

set -u

WARN_PERCENT="${DISK_WARN_PERCENT:-90}"
CRIT_PERCENT="${DISK_CRIT_PERCENT:-95}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

echo ""
echo "Disk Pressure Check"
echo "==================="
echo ""

root_line="$(df -hP / | awk 'NR==2 {print $2, $3, $4, $5}')"
read -r root_size root_used root_avail root_pct <<< "${root_line}"
root_pct_num="${root_pct%%%}"

status_color="${GREEN}"
status_text="OK"
if [ "${root_pct_num}" -ge "${CRIT_PERCENT}" ]; then
    status_color="${RED}"
    status_text="CRITICAL"
elif [ "${root_pct_num}" -ge "${WARN_PERCENT}" ]; then
    status_color="${YELLOW}"
    status_text="WARN"
fi

printf "Root filesystem: %b%s%b  used=%s  avail=%s  total=%s\n" "${status_color}" "${status_text}" "${NC}" "${root_used}" "${root_avail}" "${root_size}"

echo ""
echo "Top local directories in the workspace:"
du -sh /home/ubuntu/hr-rag-chatbot/* 2>/dev/null | sort -h | tail -n 10

if command -v docker >/dev/null 2>&1; then
    echo ""
    echo "Docker disk usage:"
    if docker system df >/dev/null 2>&1; then
        docker system df
    else
        echo "docker present but current user cannot read Docker usage."
    fi
fi

echo ""
