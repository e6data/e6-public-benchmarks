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
WARNINGS=0

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
    if [ ! -s "$j" ]; then
        FOUND_BAD=true
        quarantine "$j" "zero bytes"
    elif ! unzip -tq "$j" >/dev/null 2>&1; then
        FOUND_BAD=true
        quarantine "$j" "invalid zip archive"
    fi
done < <(find "$JMETER_DIR" -name "*.jar" -type f 2>/dev/null)
$FOUND_BAD || echo -e "  ${GREEN}ok${NC} - none"
echo ""

# --- 3. Embedded dependency diagnostics ----------------------------------
echo "3. Embedded logging / Netty dependencies"
for j in "${E6_JARS[@]}"; do
    [ -f "$j" ] || continue
    if unzip -l "$j" 2>/dev/null | grep -q 'org/slf4j/impl/StaticLoggerBinder.class'; then
        echo -e "  ${YELLOW}warning${NC} - $(basename "$j") embeds an SLF4J 1.x binding; JMeter may report multiple bindings"
        WARNINGS=$((WARNINGS + 1))
    fi
    if unzip -l "$j" 2>/dev/null | grep -q 'io/netty/'; then
        echo -e "  ${YELLOW}warning${NC} - $(basename "$j") embeds Netty classes; JMeter class scanning may log ignored IllegalAccessError messages"
        WARNINGS=$((WARNINGS + 1))
    fi
done
[ "$WARNINGS" -eq 0 ] && echo -e "  ${GREEN}ok${NC} - no embedded conflicts detected"
echo ""

# --- Result ---------------------------------------------------------------
echo "=========================================="
if [ "$MOVED" -eq 0 ]; then
    echo -e "${GREEN}No actionable duplicate or corrupt jars found.${NC}"
else
    if $DRY_RUN; then
        echo -e "${YELLOW}${MOVED} jar(s) would be quarantined. Re-run without --dry-run.${NC}"
    else
        echo -e "${GREEN}${MOVED} jar(s) quarantined to lib_quarantine/${NC}"
        echo "Restore with: mv ${QUARANTINE}/<jar> ${JMETER_DIR}/lib/ext/"
    fi
fi
[ "$WARNINGS" -gt 0 ] && echo -e "${YELLOW}${WARNINGS} non-actionable fat-jar warning(s); prefer a vendor-approved thin/shaded driver when available.${NC}"
echo "=========================================="
echo ""
echo "e6 driver(s) now on the classpath:"
find "$JMETER_DIR" -name "e6-jdbc-driver-*.jar" 2>/dev/null | sed "s|^|  |" || echo "  (none)"
