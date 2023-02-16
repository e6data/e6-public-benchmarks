import csv
import datetime
import logging
import os
import threading
import time
from multiprocessing import Pool
from pathlib import Path

import boto3
import psutil
from pyathena import connect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

ENGINE = 'Athena'

DB_NAME = os.getenv("DB_NAME")
ATHENA_BUCKET = os.getenv("ATHENA_BUCKET")
QUERY_CSV_COLUMN_NAME = os.getenv("QUERY_CSV_COLUMN_NAME") or 'QUERY'
INPUT_CSV_PATH = os.getenv('INPUT_CSV_PATH')
CONCURRENT_QUERY_COUNT = int(os.getenv("CONCURRENT_QUERY_COUNT") or 5)
CONCURRENCY_INTERVAL = int(os.getenv("CONCURRENCY_INTERVAL") or 5)

REGION = os.getenv("REGION") or "us-east-1"
QUERYING_MODE = os.getenv('QUERYING_MODE') or "SEQUENTIAL"  # or 'CONCURRENT'
QUERY_INPUT_TYPE = 'CSV_PATH'

AWS_ASSUME_ROLE_ARN = os.getenv("AWS_ASSUME_ROLE_ARN") or None  # Optional
ASSUME_ROLE_MODE = os.getenv("ASSUME_ROLE_MODE") == 'true'  # True if querying in athena is to be done by assuming role

TEST_DB_EPOC_TIME = datetime.datetime.now().strftime('%s')
os.environ['TEST_DB_EPOC_TIME'] = TEST_DB_EPOC_TIME
ATHENA_BUCKET_PATH = "s3://{}/Athena/{}".format(ATHENA_BUCKET, TEST_DB_EPOC_TIME)


class QueryException(Exception):
    pass


def create_readable_name_from_key_name(key: str) -> str:
    return key.lower().replace('_', ' ').capitalize()


def create_athena_con(db_name=DB_NAME):
    logger.info(f'TIMESTAMP : {datetime.datetime.now()} Connecting to athena database...')
    now = time.time()
    try:
        if ASSUME_ROLE_MODE:
            athena_conn = connect(
                s3_staging_dir=ATHENA_BUCKET_PATH,
                region_name=REGION,
                schema_name=DB_NAME,
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                aws_session_token=os.getenv('AWS_SESSION_TOKEN')
            )
        else:
            athena_conn = connect(
                s3_staging_dir=ATHENA_BUCKET_PATH,
                region_name=REGION,
                schema_name=DB_NAME
            )

        logger.info('Connected to athena in {}'.format(time.time() - now))
        return athena_conn
    except Exception as e:
        logger.error(e)
        logger.error(
            'TIMESTAMP : {} Failed to connect to athena | database with {}'.format(datetime.datetime.now(), db_name)
        )


def athena_query_method(row):
    """
    ONLY FOR CONCURRENCY QUERIES
    """
    query_alias_name = row.get('query_alias_name')
    query = row.get('query').replace('\n', ' ').replace('  ', ' ')
    db_name = row.get('db_name') or DB_NAME
    local_connection = create_athena_con()
    logger.info(
        'TIMESTAMP : {} connected with db {} '.format(datetime.datetime.now(), db_name))
    local_cursor = local_connection.cursor()
    logger.info('TIMESTAMP : {} Executing Query: {}'.format(datetime.datetime.now(), query))
    logger.info('Query alias: {}, Started at: {}'.format(query_alias_name, datetime.datetime.now()))
    status = query_on_athena(query, local_cursor)
    logger.info('Query alias: {}, Ended at: {}'.format(query_alias_name, datetime.datetime.now()))
    try:
        local_cursor.close()
        local_connection.close()
    except Exception as e:
        logger.error("CURSOR CLOSE FAILED : {}".format(str(e)))
    return status, query_alias_name, query, db_name


def query_on_athena(query, cursor) -> dict:
    query_start_time = datetime.datetime.now()
    try:
        cursor.execute(query)
        cursor.fetchall()
        query_end_time = datetime.datetime.now()
        row_count = cursor.rownumber
        query_id = cursor.query_id
        try:
            bytes_scanned = round(cursor.data_scanned_in_bytes / (1024 * 1024 * 1024), 3)
        except:
            bytes_scanned = "Not available"
        try:
            execution_time_from_engine = cursor.engine_execution_time_in_millis / 1000
        except:
            execution_time_from_engine = "Not available"
        query_status = 'Success'

        return dict(
            query_id=query_id,
            row_count=row_count,
            bytes_scanned_in_GB=bytes_scanned,
            execution_time=execution_time_from_engine,
            client_perceived_time=round((query_end_time - query_start_time).total_seconds(), 3),
            query_status=query_status,
            start_time=query_start_time,
            end_time=query_end_time,
            err_msg=None,
        )
    except Exception as e:
        logger.info('TIMESTAMP {} Error on querying Athena engine: {}'.format(datetime.datetime.now(), e))
        query_status = 'Failure'
        err_msg = str(e)
        query_end_time = datetime.datetime.now()
        if 'timeout' in err_msg:
            err_msg = 'Connect timeout. Unable to connect.'
        return dict(
            query_id=None,
            row_count=0,
            bytes_scanned_in_GB=0,
            execution_time=0,
            client_perceived_time=0,
            query_status=query_status,
            start_time=query_start_time,
            end_time=query_end_time,
            err_msg=err_msg,
        )


class AthenaBenchmark:
    current_retry_count = 1
    max_retry_count = 5
    retry_sleep_time = 5  # Seconds

    def __init__(self):
        self.execution_start_time = datetime.datetime.now()
        self.total_number_of_queries = 0
        self.total_number_of_queries_successful = 0
        self.total_number_of_queries_failed = 0
        self.failed_query_alias = []

        self.db_list = list()

        self.athena_connection = None
        self.athena_cursor = None
        self.local_file_path = None

        self.db_conn_retry_count = 0

        self._check_envs()

        self.counter = 0
        self.failed_query_count = 0
        self.success_query_count = 0
        self.query_results = list()
        self.local_file_path = None
        if ASSUME_ROLE_MODE:
            self.generate_sts_token()

        result, is_any_query_failed = self._perform_query_from_csv()
        self._send_V2_summary()
        self._generate_csv_report(result)
        if is_any_query_failed:
            msg = 'Some queries failed. Please check the above logs for more information.'
            logger.error(msg)
            """
            Raise Exception if any query failed to execute.
            Based on this, Jenkins will display build failed.
            """
            raise QueryException(msg)

    def _send_V2_summary(self):
        current_timestamp = datetime.datetime.now()
        failed_query_message = self.total_number_of_queries_failed
        if failed_query_message > 0:
            try:
                failed_query_message = '{} (Query Alias: {})'.format(
                    failed_query_message,
                    ', '.join(self.failed_query_alias)
                )
            except:
                failed_query_message = 'Failed Query Alias not available'
        test_run_date = f'{self.execution_start_time:%d-%m-%Y %H:%M:%S}'
        summary_data = {
            'Engine': ENGINE,
            'Test Run Date': test_run_date,
            'Dataset': DB_NAME,
            'Total Run Time': str(current_timestamp - self.execution_start_time).split('.')[0],
            'Total Queries Run': self.total_number_of_queries,
            'Total Queries Successful': self.total_number_of_queries_successful,
            'Total Queries Failed': failed_query_message,
        }
        data = 'Summary \n'
        for key, value in summary_data.items():
            data += '{} - {} \n'.format(key, value)
        logger.info("SUMMARY\n" + data)

    def _check_envs(self):
        if not QUERY_INPUT_TYPE:
            raise QueryException('Invalid QUERY_INPUT_TYPE: Please set the environment.')
        if not INPUT_CSV_PATH:
            raise QueryException('Invalid INPUT_CSV_PATH: Please set the environment.')
        if not DB_NAME:
            raise QueryException('SET DB_NAME as environment variable.')
        if not os.getenv("ATHENA_BUCKET"):
            raise QueryException('SET ATHENA_BUCKET as environment variable.It is used in saving query results.')

    def generate_sts_token(self):
        """
        Function for generating sts token using assume role.
        """
        _sts_client = boto3.client('sts')
        _assumed_role_object = _sts_client.assume_role(
            RoleArn=AWS_ASSUME_ROLE_ARN,
            RoleSessionName="AssumeRoleSession"
        )
        _credentials = _assumed_role_object['Credentials']
        os.environ['AWS_ACCESS_KEY_ID'] = _credentials['AccessKeyId']
        os.environ['AWS_SECRET_ACCESS_KEY'] = _credentials['SecretAccessKey']
        os.environ['AWS_SESSION_TOKEN'] = _credentials['SessionToken']

    def _get_query_list_from_csv_file(self):
        self.local_file_path = INPUT_CSV_PATH
        logger.info('Local file path {}'.format(self.local_file_path))
        logger.info('Reading data from file...')
        data = list()
        with open(self.local_file_path, 'r') as fh:
            reader = csv.DictReader(fh)
            csv_data = [i for i in reader]
            for row in csv_data:
                data.append({
                    'query': row.get(QUERY_CSV_COLUMN_NAME) or row.get('query'),
                    'query_alias_name': row.get('QUERY_ALIAS') or row.get('query_alias_name'),
                    'db_name': DB_NAME,
                    'result_correctness_check': 0,
                    'query_num': None,
                    'group_id': None,
                    'query_category': None
                })

        self.total_number_of_queries = len(csv_data)
        return data

    def _perform_query_from_csv(self):
        logger.info('Performing query on athena from cloud storage file (eg S3)')

        all_rows = self._get_query_list_from_csv_file()
        if QUERYING_MODE == "CONCURRENT":
            self.total_number_of_threads = CONCURRENT_QUERY_COUNT
            self.time_wait = CONCURRENCY_INTERVAL
            self.total_number_of_threads = int(self.total_number_of_threads)
            self.time_wait = int(self.time_wait)

            pool_pool = list()
            size = self.total_number_of_threads
            loop_count = (len(all_rows) / self.total_number_of_threads)
            concurrent_looper = int(loop_count) + 1 if type(loop_count) == float else loop_count
            for j in range(concurrent_looper):
                pool = Pool(processes=size)
                res = pool.map_async(athena_query_method, (i for i in all_rows[size * j:size * (j + 1)]))
                pool_pool.append(res)
                time.sleep(self.time_wait)
            logger.info("Running concurrent queries in ATHENA with ENABLE_CONCURRENCY enabled")
            for j in pool_pool:
                for output in j.get():
                    status, query_alias_name, query, db_name = output[0], output[1], output[2], output[3]

                    if status.get('query_status') == 'Failure':
                        self.failed_query_count += 1
                        self.failed_query_alias.append(query_alias_name)
                    else:
                        self.success_query_count += 1
                    self.query_results.append(dict(
                        s_no=self.counter + 1,
                        query_alias_name=query_alias_name,
                        query_text=query,
                        db_name=db_name,
                        **status
                    ))
                    logger.info(dict(
                        s_no=self.counter + 1,
                        query_alias_name=query_alias_name,
                        query_text=query,
                        db_name=db_name,
                        **status
                    ))
                    logger.info('{}. Query status of query alias: {} {}'.format(
                        self.counter,
                        query_alias_name,
                        status.get('query_status'))
                    )
                    self.counter += 1
        else:
            for row in all_rows:
                logger.info("Running sequential queries in ATHENA with ENABLE_CONCURRENCY disabled")
                status, query_alias_name, query, db_name = athena_query_method(row)
                err_msg = status.pop('err_msg')
                self.query_results.append(dict(
                    **status,
                    query_alias_name=query_alias_name,
                    query_text=query,
                    db_name=db_name,
                    err_msg=err_msg
                ))
                if status.get('query_status') == 'Failure':
                    self.failed_query_count += 1
                    self.failed_query_alias.append(query_alias_name)
                else:
                    self.success_query_count += 1
                self.query_results.append(dict(
                    s_no=self.counter + 1,
                    query_alias_name=query_alias_name,
                    query_text=query,
                    db_name=db_name,
                    **status
                ))
                logger.info(dict(
                    s_no=self.counter + 1,
                    query_alias_name=query_alias_name,
                    query_text=query,
                    db_name=db_name,
                    **status
                ))
                logger.info('{}. Query status of query alias: {} {}'.format(
                    self.counter,
                    query_alias_name,
                    status.get('query_status'))
                )
                self.counter += 1

        logger.info('TIMESTAMP {} ALL Query completed'.format(datetime.datetime.now()))
        self.total_number_of_queries = len(all_rows)
        self.total_number_of_queries_successful = self.success_query_count
        self.total_number_of_queries_failed = self.failed_query_count

        logger.info('Total failed query: {}'.format(self.failed_query_count))
        logger.info('Total success query: {}'.format(self.success_query_count))
        is_any_query_failed = self.failed_query_count > 0
        return self.query_results, is_any_query_failed

    def _generate_csv_report(self, result):
        """
        DB name, Query Alias, Query Text, Query ID, Query Status, Execution Time, Client Perceived Time,bytes_scanned_in_GB
        Row Count , Error message, Start Time, End Time, (edited)
        """
        column_order = ['db_name', 'query_alias_name', 'query_text', 'query_id', 'query_status', 'execution_time',
                        'client_perceived_time', 'row_count', 'bytes_scanned_in_GB', 'err_msg', 'start_time',
                        'end_time']
        path = Path(__file__).resolve().parent
        today = datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S')
        file_name = f'athena_results_{today}.csv'
        result_file_path = os.path.join(path, file_name)
        logger.info('Result local file path {}'.format(result_file_path))
        with open(result_file_path, 'w', newline='') as fp:
            header_list = [create_readable_name_from_key_name(i) for i in column_order]
            writer = csv.writer(fp, delimiter=',')
            writer.writerow(header_list)
            for line in result:
                ordered_data = list()
                for k in column_order:
                    ordered_data.append(line.get(k))
                writer.writerow(ordered_data)


def ram_cpu_calculation(period):
    while True:
        mem_usage = psutil.virtual_memory()
        cpu_usage = psutil.cpu_percent(period)
        logger.info(
            f"TIMESTAMP : {datetime.datetime.now()} RAM USAGE: {mem_usage.used / (1024 ** 3):.2f}G CPU USAGE {cpu_usage}%")


if __name__ == '__main__':
    logger.info('Engine is {}'.format(os.getenv("ENGINE")))

    a = threading.Thread(target=ram_cpu_calculation, args=(5,))
    a.daemon = True
    a.start()
    AthenaBenchmark()
