import datetime
import os

"""
For e6data
"""
ENGINE_IP = os.getenv("ENGINE_IP")
DB_NAME = os.getenv("DB_NAME")
QUERY_CSV_COLUMN_NAME = os.getenv("QUERY_CSV_COLUMN_NAME") or 'QUERY'
INPUT_CSV_PATH = os.getenv('INPUT_CSV_PATH')
CONCURRENT_QUERY_COUNT = int(os.getenv("CONCURRENT_QUERY_COUNT") or 5)
CONCURRENCY_INTERVAL = int(os.getenv("CONCURRENCY_INTERVAL") or 5)
QUERYING_MODE = os.getenv('QUERYING_MODE') or "SEQUENTIAL"
QUERY_INPUT_TYPE = 'CSV_PATH'  # mysql or csv
E6_USER = os.getenv("E6_USER")
E6_TOKEN = os.getenv("E6_TOKEN")
"""
For Athena
"""
RESULT_BUCKET = os.getenv("RESULT_BUCKET")
GLUE_REGION = os.getenv("GLUE_REGION") or "us-east-1"
RESULT_BUCKET_PATH = "s3://{}/Athena/{}".format(RESULT_BUCKET, datetime.datetime.now().strftime('%s'))

"""
For Trino
"""
ENGINE_PORT = int(os.getenv("ENGINE_PORT") or 8889)
TRINO_USER = os.getenv("TRINO_USER") or "test"
TRINO_CATALOG = os.getenv("TRINO_CATALOG") or "test"