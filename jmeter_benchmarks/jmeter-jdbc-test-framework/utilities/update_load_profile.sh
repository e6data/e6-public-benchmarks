#!/bin/bash

# Script to update JMeter JMX file with load profile from CSV file
# Usage: ./update_load_profile.sh <load_profile.csv> <test_plan.jmx>

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check arguments
if [ $# -ne 2 ]; then
    echo "Usage: $0 <load_profile.csv> <test_plan.jmx>"
    echo "Example: $0 test_properties/load_profile.csv Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx"
    exit 1
fi

LOAD_PROFILE="$1"
JMX_FILE="$2"

# Check if files exist
if [ ! -f "$LOAD_PROFILE" ]; then
    echo -e "${RED}❌ Load profile file not found: $LOAD_PROFILE${NC}"
    exit 1
fi

if [ ! -f "$JMX_FILE" ]; then
    echo -e "${RED}❌ JMX file not found: $JMX_FILE${NC}"
    exit 1
fi

echo "================================================================================"
echo -e "${BLUE}🚀 JMeter Load Profile Updater${NC}"
echo "================================================================================"

# Create backups directory if it doesn't exist
BACKUP_DIR="backups"
mkdir -p "$BACKUP_DIR"

# Clean up old backup files (keep only last 3 backups)
JMX_BASE=$(basename "$JMX_FILE")
OLD_BACKUPS=$(ls -1t "${BACKUP_DIR}/${JMX_BASE}.backup_"* 2>/dev/null | tail -n +4)
if [ -n "$OLD_BACKUPS" ]; then
    echo -e "${BLUE}🧹 Cleaning up old backups...${NC}"
    echo "$OLD_BACKUPS" | xargs rm -f
    CLEANED_COUNT=$(echo "$OLD_BACKUPS" | wc -l)
    echo -e "${GREEN}   Removed $CLEANED_COUNT old backup(s)${NC}"
fi

# Create backup in backups directory
BACKUP_FILE="${BACKUP_DIR}/${JMX_BASE}.backup_$(date +%Y%m%d_%H%M%S)"
cp "$JMX_FILE" "$BACKUP_FILE"
echo -e "${GREEN}💾 Created backup: $BACKUP_FILE${NC}"

# Function to generate hash for collection property name
generate_hash() {
    local input="$1"
    # Use cksum to generate a consistent hash
    echo "$input" | cksum | cut -d' ' -f1
}

# Read load profile and generate XML schedule
echo -e "\n${BLUE}📖 Reading load profile: $LOAD_PROFILE${NC}"

# Initialize variables
TOTAL_QUERIES=0
TOTAL_DURATION=0
SCHEDULE_XML=""
STEP=0

# Read CSV file (skip header)
while IFS=',' read -r start_value end_value duration; do
    # Skip header and empty lines
    if [ "$start_value" = "StartValue" ] || [ -z "$start_value" ]; then
        continue
    fi
    
    # Remove any whitespace and carriage returns
    start_value=$(echo "$start_value" | tr -d ' \r')
    end_value=$(echo "$end_value" | tr -d ' \r')
    duration=$(echo "$duration" | tr -d ' \r')
    
    # Skip if any value is empty
    if [ -z "$start_value" ] || [ -z "$end_value" ] || [ -z "$duration" ]; then
        continue
    fi
    
    STEP=$((STEP + 1))
    
    # Calculate queries for this step
    AVG_QPS=$(( (start_value + end_value) / 2 ))
    QUERIES_THIS_STEP=$(( AVG_QPS * duration ))
    TOTAL_QUERIES=$(( TOTAL_QUERIES + QUERIES_THIS_STEP ))
    TOTAL_DURATION=$(( TOTAL_DURATION + duration ))
    
    echo "  Step $STEP: ${start_value}-${end_value} QPS for ${duration}s = ${QUERIES_THIS_STEP} queries"
    
    # Generate hash for this entry
    HASH=$(generate_hash "${start_value}_${end_value}_${duration}")
    
    # Build XML for this schedule entry
    SCHEDULE_XML="${SCHEDULE_XML}          <collectionProp name=\"${HASH}\">
            <stringProp name=\"48\">${start_value}</stringProp>
            <stringProp name=\"49\">${end_value}</stringProp>
            <stringProp name=\"50\">${duration}</stringProp>
          </collectionProp>
"
    
done < "$LOAD_PROFILE"

# Calculate time formatting
HOURS=$(( TOTAL_DURATION / 3600 ))
MINUTES=$(( (TOTAL_DURATION % 3600) / 60 ))
SECONDS=$(( TOTAL_DURATION % 60 ))

# Calculate expected completion time
CURRENT_TIME=$(date +%s)
COMPLETION_TIME=$(( CURRENT_TIME + TOTAL_DURATION ))
COMPLETION_FORMATTED=$(date -r $COMPLETION_TIME '+%Y-%m-%d %H:%M:%S')

echo -e "\n${GREEN}📊 Load Profile Summary:${NC}"
echo -e "${GREEN}   • Total expected queries: $TOTAL_QUERIES${NC}"
echo -e "${GREEN}   • Total test duration: ${TOTAL_DURATION}s (${HOURS}h ${MINUTES}m ${SECONDS}s)${NC}"
echo -e "${GREEN}   • Expected completion: $COMPLETION_FORMATTED${NC}"

# Create complete Schedule XML block
COMPLETE_SCHEDULE="        <collectionProp name=\"Schedule\">
${SCHEDULE_XML}        </collectionProp>"

# Create a temporary file for the modified JMX
TEMP_FILE=$(mktemp)

# Process the JMX file
echo -e "\n${BLUE}📝 Updating JMX file: $JMX_FILE${NC}"

# State tracking for XML processing
IN_SCHEDULE=0
SCHEDULE_FOUND=0
SKIP_LINES=0

# Process the JMX file line by line
while IFS= read -r line; do
    # Check if we're entering a Schedule block
    if [[ "$line" == *"<collectionProp name=\"Schedule\">"* ]]; then
        IN_SCHEDULE=1
        SCHEDULE_FOUND=1
        SKIP_LINES=1
        # Write the new schedule
        echo "$COMPLETE_SCHEDULE" >> "$TEMP_FILE"
    # Check if we're exiting the Schedule block
    elif [[ "$line" == *"</collectionProp>"* ]] && [ $IN_SCHEDULE -eq 1 ]; then
        # Check if this is a nested collectionProp
        if [[ "$line" == *"          </collectionProp>"* ]]; then
            # This is a nested entry, skip it
            continue
        else
            # This is the closing tag for Schedule
            IN_SCHEDULE=0
            SKIP_LINES=0
            continue
        fi
    # Skip lines inside the old Schedule block
    elif [ $SKIP_LINES -eq 1 ]; then
        continue
    # Write all other lines
    else
        echo "$line" >> "$TEMP_FILE"
    fi
done < "$JMX_FILE"

# Check if schedule was found and updated
if [ $SCHEDULE_FOUND -eq 1 ]; then
    # Move the temporary file to the original
    mv "$TEMP_FILE" "$JMX_FILE"
    echo -e "${GREEN}✅ Successfully updated schedule with $STEP entries${NC}"
    
    # Verify the update
    echo -e "\n${BLUE}🔍 Verifying update...${NC}"
    
    # Count schedule entries in the updated file
    ENTRY_COUNT=$(grep -c "<collectionProp name=\"[0-9]*\">" "$JMX_FILE" 2>/dev/null || echo "0")
    
    if [ "$ENTRY_COUNT" -gt 0 ]; then
        echo -e "${GREEN}✓ Found $ENTRY_COUNT schedule entries in the updated JMX file${NC}"
        
        echo "================================================================================"
        echo -e "${GREEN}✅ SUCCESS! JMX file updated with load profile${NC}"
        echo -e "${GREEN}📈 Expected: $TOTAL_QUERIES queries${NC}"
        echo "================================================================================"
    else
        echo -e "${RED}❌ Verification failed - no schedule entries found${NC}"
        # Restore from backup
        cp "$BACKUP_FILE" "$JMX_FILE"
        echo -e "${YELLOW}⚠️  Restored from backup${NC}"
        exit 1
    fi
else
    echo -e "${RED}❌ No Schedule property found in the JMX file!${NC}"
    rm -f "$TEMP_FILE"
    exit 1
fi

echo -e "\n${BLUE}💡 To test the updated plan, run:${NC}"
echo "   ./run_jmeter_tests_interactive.sh"