#!/bin/bash
# Resolve JDBC driver conflicts in an existing JMeter installation.
#
# Usage: ./utilities/fix_jmeter_jar_conflicts.sh [--dry-run]
#
# Fixes two classpath problems that produce confusing runtime failures:
#
#   1. Multiple e6 JDBC driver versions on the classpath. The JVM loads
#      whichever it finds first, and load order depends on the filesystem,
#      so an old driver can silently win on one machine and not another.
#      Symptom: every query fails immediately with
#      "UNIMPLEMENTED: No cluster-name header or unknown cluster".
#
#   2. Zero-byte / corrupt jars, which break javac with "zip file is empty"
#      (this is what stops utilities/test_jdbc_connection.sh from compiling).
#
# Nothing is deleted: files move to lib_quarantine/ so they can be restored.
#
# NOTE: this deliberately does NOT touch JMeter's bundled Netty jars
# (lib/netty-*.jar). The e6 driver bundles gRPC plus its own Netty, but it
# is NOT self-sufficient - removing JMeter's Netty makes gRPC fail with
# "NoClassDefFoundError: Could not initialize class
# io.grpc.netty.NettyChannelBuilder" and zero samples are collected.
# Verified by testing: removing them breaks a working install.

set -e

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

DRY_RUN=false
[ "${1:-}" = "--dry-run" ] && DRY_RUN=true

JMETER_DIR="${JMETER_HOME:-}"
if [ -z "$JMETER_DIR" ] || [ ! -d "$JMETER_DIR" ]; then
    JMETER_DIR="$PROJECT_ROOT/apache-jmeter-5.6.3"
fi

if [ ! -d "$JMETER_DIR/lib" ]; then
    echo -e "${RED}Error: no JMeter installation at ${JMETER_DIR}${NC}"
    echo "Set JMETER_HOME or run ./setup_jmeter.sh first."
    exit 1
fi

QUARANTINE="$JMETER_DIR/lib_quarantine"
echo -e "${BLUE}JMeter:     ${JMETER_DIR}${NC}"
echo -e "${BLUE}Quarantine: ${QUARANTINE}${NC}"
$DRY_RUN && echo -e "${YELLOW}DRY RUN - nothing will be moved${NC}"
echo ""

MOVED=0

quarantine() {
    local f="$1" why="$2"
    [ -e "$f" ] || return 0
    echo -e "  ${YELLOW}quarantine${NC} $(basename "$f")  ${BLUE}(${why})${NC}"
    if ! $DRY_RUN; then
        mkdir -p "$QUARANTINE"
        mv "$f" "$QUARANTINE/"
    fi
    MOVED=$((MOVED + 1))
}

# --- 1. Keep only the newest e6 JDBC driver -------------------------------
echo "1. e6 JDBC driver versions"
E6_JARS=()
while IFS= read -r _j; do
    [ -n "$_j" ] && E6_JARS+=("$_j")
done < <(find "$JMETER_DIR" -name "e6-jdbc-driver-*.jar" 2>/dev/null | sort)

if [ "${#E6_JARS[@]}" -eq 0 ]; then
    echo -e "  ${RED}none found${NC} - copy one into jdbc_drivers/ and run ./setup_jmeter.sh"
elif [ "${#E6_JARS[@]}" -eq 1 ]; then
    echo -e "  ${GREEN}ok${NC} - exactly one: $(basename "${E6_JARS[0]}")"
else
    KEEP=$(printf '%s\n' "${E6_JARS[@]}" \
        | sed 's/.*e6-jdbc-driver-\([0-9.]*\)-.*/\1 &/' \
        | sort -V -k1,1 | tail -1 | cut -d' ' -f2-)
    echo -e "  ${GREEN}keep${NC} $(basename "$KEEP")"
    for j in "${E6_JARS[@]}"; do
        [ "$j" = "$KEEP" ] || quarantine "$j" "older/duplicate e6 driver"
    done
fi
echo ""

# --- 2. Corrupt / empty jars ----------------------------------------------
echo "2. Zero-byte or corrupt jars"
FOUND_BAD=false
while IFS= read -r j; do
    FOUND_BAD=true
    quarantine "$j" "zero bytes"
done < <(find "$JMETER_DIR" -name "*.jar" -size 0 2>/dev/null)
$FOUND_BAD || echo -e "  ${GREEN}ok${NC} - none"
echo ""

# --- Result ---------------------------------------------------------------
echo "=========================================="
if [ "$MOVED" -eq 0 ]; then
    echo -e "${GREEN}Classpath is clean - nothing to do.${NC}"
else
    if $DRY_RUN; then
        echo -e "${YELLOW}${MOVED} jar(s) would be quarantined. Re-run without --dry-run.${NC}"
    else
        echo -e "${GREEN}${MOVED} jar(s) quarantined to lib_quarantine/${NC}"
        echo "Restore with: mv ${QUARANTINE}/<jar> ${JMETER_DIR}/lib/ext/"
    fi
fi
echo "=========================================="
echo ""
echo "e6 driver(s) now on the classpath:"
find "$JMETER_DIR" -name "e6-jdbc-driver-*.jar" 2>/dev/null | sed "s|^|  |" || echo "  (none)"
