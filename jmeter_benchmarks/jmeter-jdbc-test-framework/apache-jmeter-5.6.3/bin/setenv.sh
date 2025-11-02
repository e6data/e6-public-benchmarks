#!/bin/sh

# JMeter Custom Environment Settings
# This file is sourced by the jmeter startup script

# Set heap memory to 2GB for both min and max, with 512MB metaspace
# Default is: -Xms1g -Xmx1g -XX:MaxMetaspaceSize=256m
export HEAP="-Xms2g -Xmx2g -XX:MaxMetaspaceSize=512m"

# Optional: Uncomment to set custom JVM arguments
# export JVM_ARGS="-Dprop=val"

# Optional: Uncomment to customize GC algorithm
# export GC_ALGO="-XX:+UseG1GC -XX:MaxGCPauseMillis=100 -XX:G1ReservePercent=20"
