## Here are the python scripts for benchmarking data analytics engines you are using with e6data within minutes

### Please follow the format of <em>sample.csv</em> file and populate your own queries before starting benchmark scripts.

### 1. Install the python dependent libraries.
```
pip install -r requirements.txt
```
### 2. Set the environment variables.
```bash
export ENGINE_IP=127.0.0.1 # Replace the value with your engine host IP
export DB_NAME=tpcds_1000 # Replace with your preferred Database
export INPUT_CSV_PATH=/Users/dummyuser/folder/query_file.csv # Replace the value with your local file path
export QUERYING_MODE=SEQUENTIAL # for concurrency runs, change the value to CONCURRENT

# In the case of concurrent benchmarking, ensure below variables are set to your requirements
# The number of queries to be fired at t1 second
export CONCURRENT_QUERY_COUNT = 20 # Default Value is 5

# The interval between subsequent set of concurrent queries to be fired 
export CONCURRENCY_INTERVAL = 10 # Default Value is 5

# Example: If your benchmarking needs 50 queries to fire every 2 seconds,
# export CONCURRENT_QUERY_COUNT = 50
# export CONCURRENCY_INTERVAL = 2

#Additional environment variables in Athena Benchmarking
export ATHENA_BUCKET=testbucketname # For storing query results
export REGION=us-east-1 # Glue region. Default Value is us-east-1
export ASSUME_ROLE_MODE=true # Default Value is false. To be Enabled if querying is to expected using assume role
export AWS_ASSUME_ROLE_ARN=arn:aws:iam::123445667:role/rolename # ARN of assume role

```

### 3. Run the python script.
For <em>e6data</em>:
```
python3 e6_benchmark.py
```
For <em>Trino</em>:
```
python3 trino_benchmark.py
```
For <em>Athena</em>:
```
python3 athena_benchmark.py
```
