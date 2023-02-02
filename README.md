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