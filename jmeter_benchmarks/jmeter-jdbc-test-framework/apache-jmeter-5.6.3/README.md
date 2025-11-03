
# JMeter Performance Test Suite

This repository contains JMeter test plans for evaluating query performance, developed by E6Data.

## Configuration

The test plans use two property files:
- `e6_connection.properties` - Manages database connection parameters
- `e6_test.properties` - Controls test behavior settings

## Prerequisites

### Java 17 Installation

#### Option 1: Package Manager

**Amazon Linux 2:**
```bash
sudo amazon-linux-extras enable corretto8
sudo yum install java-17-amazon-corretto-devel
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install openjdk-17-jdk
```

#### Option 2: Manual Installation
```bash
wget https://download.java.net/java/GA/jdk17.0.2/dfd4a8d0985749f896bed50d7138ee7f/8/GPL/openjdk-17.0.2_linux-x64_bin.tar.gz
tar -xvf openjdk-17.0.2_linux-x64_bin.tar.gz
sudo mv jdk-17.0.2 /usr/local/
```

#### Verification:
```bash
java -version
export JAVA_HOME=/usr/lib/jvm/java-17-amazon-corretto.aarch64
echo "export JAVA_HOME=/usr/lib/jvm/java-17-amazon-corretto.aarch64" >> ~/.bashrc
source ~/.bashrc
```

### jq Installation

**Amazon Linux:**
```bash
# For Amazon Linux 2:
sudo yum install -y jq

# For Amazon Linux 2023:
sudo dnf install -y jq

# Verify:
jq --version
```

## Running Tests

Execute the interactive test runner:
```bash
./run_jmeter_tests_interactive.sh
```

## File Structure

```
.
├── README.md
├── e6_connection.properties
├── e6_test.properties
├── run_jmeter_tests_interactive.sh
└── test_plans/
    └── [JMX test files]
```

## Property Files

Sample configurations:

**e6_connection.properties:**
```properties
# Connection settings
db.host=your_host
db.port=5432
db.name=your_db
```

**e6_test.properties:**
```properties
# Test parameters
test.duration=600
query.iterations=1000
```

## Support

Contact the performance team for assistance.

