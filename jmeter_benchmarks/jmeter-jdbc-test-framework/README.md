# JMeter JDBC Test Framework

Framework to run **JMeter JDBC test plans** for database load and performance testing.

## 🔹 Key Features
- **Pre-configured JMeter test plans** that use `.properties` files to make test execution simple, reusable, and automation-friendly.  
  - Connection parameters are defined in a `connection_properties` file inside the `connection_properties/` folder  
  - Test parameters are defined in a `test_properties` file inside the `test_properties/` folder  
  - Queries are stored in a `.csv` file inside the `data_files/` folder  

- **Flexible query execution**:  
  Queries are read from a CSV file, making this framework flexible to run queries against a database using:  
  - Connection settings from the `connection_properties` file  
  - Test parameters from the `test_properties` file  
  - Queries from the `data_files` CSV  

- **Simple setup**:  
  You only need to:  
  1. Create a `connection_properties` file in the `connection_properties/` folder  
  2. Create a `test_properties` file in the `test_properties/` folder  
  3. Add your queries as a `.csv` file in the `data_files/` folder  

- **Multi-database support**:  
  The JMeter JDBC test plans can run against multiple databases that support JDBC connections (e.g., **E6Data, Databricks, etc.**) using the appropriate `.properties` file.  

- **Wrapper scripts**:  
  Includes helper scripts that can run the JMeter tests by taking user inputs interactively from the above folders through the command prompt.  

## Prerequisites

### Java 17 should be installed

#### Steps to install java - Option 1 using package manager

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

#### Steps to install java - Option 2: Manual Installation
```bash
wget https://download.java.net/java/GA/jdk17.0.2/dfd4a8d0985749f896bed50d7138ee7f/8/GPL/openjdk-17.0.2_linux-x64_bin.tar.gz
tar -xvf openjdk-17.0.2_linux-x64_bin.tar.gz
sudo mv jdk-17.0.2 /usr/local/
```

#### Set the JAVA_HOME:
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
jq -V
```

### Install git - If not installed
```
sudo yum install git
```

### Clone the repo
```
git clone https://github.com/george-pc/jmeter-jdbc-test-framework.git
```

### change to the cloned directory
```
cd jmeter-jdbc-test-plans/
```

### create a reports directory if not exists
```
mkdir reports
```

# Running Tests using standard jmeter CLI command.
### Create the connection properties files with the required connection using the template/sample properties file

```bash
cd connection_properties
cp sample_connection.properties <YOUR_DB_SERVER>_connection.properties
```

### Create the test properties files with the test parameters using the template/sample properties file
```bash
cd test_properties
cp sample_test.properties <YOUR_TEST>_test.properties```
```

### Create/copy the queries to the data_files folder as a .csv file
```bash
cd data_files
cp <YOUR_TEST_QUERIES>.csv data_files
```

## Run Tests using standard jmeter CLI command.
Once the properties file are created, we can run the prebuilt test plan using above created files as input to run the test against your taget system
```bash
$JMETER_BIN/jmeter -n -t "$TEST_PLAN" -l "$REPORT_PATH/results.jtl" -q "$TEST_PROPERTIES" -q "$CONNECTION_PROPERTIES" -JQUERY_PATH=$QUERIES_FILE
```

## Example - Run Jmeter in GUI mode:
```bash
./apache-jmeter-5.6.3/bin/jmeter -t Test-Plans/Test-Plan-Maintain-static-concurrency.jmx -q connection_properties/sample_connection.properties -q test_properties/sample_test.properties
```
## Example - Run Jmeter in Non GUI mode:
```bash
./apache-jmeter-5.6.3/bin/jmeter -n -t Test-Plans/Test-Plan-Maintain-static-concurrency.jmx -q connection_properties/sample_connection.properties  -q test_properties/sample_test.properties
```


# Running Tests interactively using the wrapper script

## Interactive Mode
Execute the interactive test runner:
```bash
./run_jmeter_tests_interactive.sh
```

## Automated Batch Testing

### E6Data Concurrency Tests
Run all concurrency levels (2, 4, 8, 12, 16) for a specific cluster size:

```bash
# Run S-2x2 (60 cores) concurrency tests
./utilities/run_e6data_all_concurrency.sh S-2x2

# Run M-4x4 (120 cores) concurrency tests
./utilities/run_e6data_all_concurrency.sh M-4x4

# Run with custom benchmark
./utilities/run_e6data_all_concurrency.sh M-4x4 tpcds_51_1tb
```

**Features:**
- Runs all concurrency levels sequentially
- Validates test input files before starting
- Logs each test to `/tmp/jmeter_test_logs/` with instance_type and query_file in name
- 30-second pause between tests
- Automatic S3 upload (if enabled in metadata)

### Databricks Concurrency Tests
Run all concurrency levels (2, 4, 8, 12, 16) for a specific cluster size:

```bash
# Run S-2x2 (~60 cores) concurrency tests
./utilities/run_databricks_all_concurrency.sh S-2x2

# Run S-4x4 (~120 cores) concurrency tests
./utilities/run_databricks_all_concurrency.sh S-4x4

# Run with custom benchmark
./utilities/run_databricks_all_concurrency.sh S-4x4 tpcds_51_1tb
```

**Features:**
- Runs all concurrency levels sequentially
- Validates test input files before starting
- Logs each test to `/tmp/jmeter_test_logs/` with instance_type and query_file in name
- 30-second pause between tests
- Automatic S3 upload (if enabled in metadata)

## File Structure

```
.
├── README.md
├── apache-jmeter-5.6.3
├── connection.properties
    └── [Connection properties file *.properties]
    └── [sample_connection.properties ]
├── data_files
    └── [CSV Queries file *.csv]
    └── [sample_queries.csv ]
├── metadata_files - optional
    └── [sample_metadata.txt - Optional required only to copy data to s3 or storage for keeping track of runs ]
├── test.properties
    └── [Test properties file *.properties]
    └── [sample_test.properties ]
    └── [load_profile.csv ]    
├── Scripts
    ├── run_jmeter_tests_interactive.sh
└── Test-Plans
    └── [JMX test files]
    └── [Test-Plan-Constant-QPM-On-Arrivals.jmx - To fire queries per minute using QPM in test.properties]
    └── [Test-Plan-Constant-QPS-On-Arrivals.jmx - To fire queries per sec using QPs in test.properties]
    └── [Test-Plan-Fire-QPM-with-load-profile.jmx - To fire queries per minute using load profile file in test.properties]
    └── [Test-Plan-Fire-QPS-with-load-profile.jmx - To fire queries per minute using load profile file in test.properties]
    └── [Test-Plan-Maintain-static-concurrency.jmx - To maintain fixed load / concurrency using concurrency in test.properties]
    └── [Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx - To maintain load/concurrency using load profile file in test.properties]


```

## Property Files Format

Sample configurations:

**sample_e6_connection.properties:**
```
# JDBC Jmeter connection properties

#Change below properties to connect to your target machine via JDBC
HOSTNAME=
PORT=80
DATABASE=
CATALOG=

USER=
PASSWORD=

#Change below for the JDBC connection URL of your target machine
CONNECTION_STRING=

#Change below to your JDBC Driver class
DRIVER_CLASS=io.e6.jdbc.driver.E6Driver

```

**sample_e6_test.properties:**
```
# E6 Jmeter Test properties

JMETER_HOME=

#Change below for Report directory path. Reports will be written in this directory
REPORT_PATH=reports

COPY_TO_S3=false
S3_REPORT_PATH=s3://

#Change below for concurrency based test plan which will maintain this concurrency. This applicable only for concurrency based plan
**CONCURRENT_QUERY_COUNT=2**

#Change below if u want to add RAMP_TIME(min) and RAMP_UP_STEPS (counts) to reach target concurrency 
RAMP_UP_TIME=1
RAMP_UP_STEPS=1

#Total time to run the test in minutes i.e hold the load. This is after ramp up time 
**HOLD_PERIOD=300**

#Change below for QPM based Test Plan which will fire below number of queries per minute. This is applicable only for QPM based test Plan
QPM=10

#Change below for QPS based Test Plan which will fire below number of queries per sec. This is applicable only for QPs based test Plan
**QPS=1**

#Change below for load_profile based Test Plan. This will be applicable only if u select the load profile Test Plan
**LOAD_PROFILE=test_properties/load_profile.csv**

#To select queries from the CSV in Random Order set below to true
RANDOM_ORDER=true

# Set below variable to true if you want to Repeat the queries in the CSV, this essentially means queries will repeat till the test duration 
**RECYCLE_ON_EOF=false**

#Change below to the absolute path of your query file
QUERY_PATH=../data_files/Benchmark_TPCDS-51-queries_without_bootstrap.csv

```
**load_profile.csv:**
```
# E6 Jmeter Test properties
StartValue,EndValue,Duration
1,1,5
2,2,10
3,3,15
4,4,20
5,5,25
```

## Important Note

- DO NOT PUT YOUR SENSITIVE LOGIN/CREDENTIALS OR ANY SUCH SENSITIVE INFO NEITHER IN PROPERTIES/JMETER TEST PLAN OR ANY SUCH FILE.
- CHECK THE .gitignore file as we avoid some sensitive info to be checked in.

## DISCLAIMER
- This is just a sample collection that can be used for jmeter testing, so please check the parameters and use proper reasonable values as improper setting can overload/damage the system
- Do not test directly on some production system without verification as the system can be overloaded if proper values are not set.

