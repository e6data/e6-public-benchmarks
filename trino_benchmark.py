import threading
from multiprocessing import Pool

import trino
import csv

import time
from pathlib import Path

from utils import get_logger, create_readable_name_from_key_name, read_from_csv, ram_cpu_usage
from utils.envs import *

ENGINE = 'Trino'

MACHINE_TYPE = 'c5.9xlarge'
max_retry_count = 10
sleep_time = 10

logger = get_logger()


class QueryException(Exception):
    pass


def e6x_query_method(row):
    """
    ONLY FOR CONCURRENCY QUERIES
    """
    client_perceived_start_time = time.time()
    query_alias_name = row.get('query_alias_name')
    query = row.get('query').replace('\n', ' ').replace('  ', ' ')
    db_name = row.get('db_name') or DB_NAME
    logger.info(
        'Query alias: {}, FIRED at: {} BEFORE CREATING CONNECTION'.format(query_alias_name, datetime.datetime.now()))
    local_connection = create_e6x_con()
    logger.info(
        'TIMESTAMP : {} connected with db {} and Engine {}'.format(datetime.datetime.now(), db_name, ENGINE_IP))
    local_cursor = local_connection.cursor()
    logger.info('TIMESTAMP : {} Executing Query: {}'.format(datetime.datetime.now(), query))
    logger.info('Query alias: {}, Started at: {}'.format(query_alias_name, datetime.datetime.now()))
    status = query_on_6ex(query, local_cursor,
                          query_alias=query_alias_name)
    client_perceived_time = round(time.time() - client_perceived_start_time, 3)
    logger.info('Query alias: {}, Ended at: {}'.format(query_alias_name, datetime.datetime.now()))
    try:
        local_cursor.close()
        local_connection.close()
    except Exception as e:
        logger.error("CURSOR CLOSE FAILED : {}".format(str(e)))
    return status, query_alias_name, query, db_name, client_perceived_time


def query_on_6ex(query, cursor, query_alias=None) -> dict:
    query_start_time = datetime.datetime.now()
    try:
        logger.info(
            'JUST BEFORE EXECUTION Query alias: {}, Started at: {}'.format(query_alias, datetime.datetime.now()))
        cursor.execute(query)
        results = cursor.fetchall()
        row_count = len(results)
        logger.info(
            'JUST AFTER FETCH MANY Query alias: {}, Ended at: {}'.format(query_alias, datetime.datetime.now()))
        query_end_time = datetime.datetime.now()
        query_status = 'Success'

        elapsed_time = cursor.stats.get('elapsedTimeMillis') / 1000
        query_id = cursor.stats.get('queryId')

        return dict(
            query_id=query_id,
            row_count=row_count,
            execution_time=elapsed_time,
            query_status=query_status,
            start_time=query_start_time,
            end_time=query_end_time,
            err_msg=None,
        )
    except Exception as e:
        logger.info('TIMESTAMP {} Error on querying e6data engine: {}'.format(datetime.datetime.now(), e))
        query_status = 'Failure'
        err_msg = str(e)
        query_end_time = datetime.datetime.now()
        if 'timeout' in err_msg:
            err_msg = 'Connect timeout. Unable to connect.'
        return dict(
            query_id=None,
            row_count=0,
            execution_time=0,
            query_status=query_status,
            start_time=query_start_time,
            end_time=query_end_time,
            err_msg=err_msg,
        )


def create_e6x_con(db_name=DB_NAME):
    logger.info(f'TIMESTAMP : {datetime.datetime.now()} Connecting to e6x database...')
    now = time.time()
    try:
        e6x_connection = trino.dbapi.connect(
            host=ENGINE_IP,
            port=ENGINE_PORT,
            user='vishal',
            catalog='hive',
            schema=db_name,
        )
        # self.e6x_cursor = self.e6x_connection.cursor()
        logger.info('TIMESTAMP : {} Connected to e6x in {}'.format(datetime.datetime.now(), time.time() - now))
        return e6x_connection
    except Exception as e:
        logger.error(e)
        logger.error(
            'TIMESTAMP : {} Failed to connect to the e6x database with {}'.format(datetime.datetime.now(), db_name)
        )


class E6XBenchmark:
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

        self.e6x_connection = None
        self.e6x_cursor = None
        self.local_file_path = None

        self.db_conn_retry_count = 0

        self._check_envs()

        self.counter = 0
        self.failed_query_count = 0
        self.success_query_count = 0
        self.query_results = list()
        self.local_file_path = None

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

    def _generate_csv_report(self, result):
        """
        DB name, Query Alias, Query Text, Query ID, Query Status, Execution Time, Client Perceived Time,
        Row Count , Error message, Start Time, End Time, (edited)
        """
        column_order = ['db_name', 'query_alias_name', 'query_text', 'query_id', 'query_status', 'execution_time',
                        'client_perceived_time', 'row_count', 'err_msg', 'start_time', 'end_time']
        path = Path(__file__).resolve().parent
        today = datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S')
        file_name = f'trino_results_{today}.csv'
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

    def _check_envs(self):
        if not ENGINE_IP:
            raise QueryException('Invalid ENGINE_IP: Please set the environment.')
        if not QUERY_INPUT_TYPE:
            raise QueryException('Invalid QUERY_INPUT_TYPE: Please set the environment.')
        if not INPUT_CSV_PATH:
            raise QueryException('Invalid INPUT_CSV_PATH: Please set the environment.')

    def _send_V2_summary(self):
        current_timestamp = datetime.datetime.now()
        failed_query_message = self.total_number_of_queries_failed
        if failed_query_message > 0:
            try:
                failed_query_message = '{} (Query Alias: {})'.format(failed_query_message,
                                                                     ', '.join(self.failed_query_alias))
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

    def _get_query_list_from_csv_file(self):
        if not DB_NAME:
            raise QueryException(
                'SET DB_NAME as environment variable.'
            )
        self.local_file_path = INPUT_CSV_PATH
        logger.info('Local file path {}'.format(self.local_file_path))
        logger.info('Reading data from file...')
        data = read_from_csv(self.local_file_path)
        self.total_number_of_queries = len(data)
        return data

    def _perform_query_from_csv(self):
        logger.info('Performing query on e6x from cloud storage file (eg S3)')

        all_rows = self._get_query_list_from_csv_file()
        if QUERYING_MODE == "CONCURRENT":
            self.total_number_of_threads = CONCURRENT_QUERY_COUNT
            self.time_wait = CONCURRENCY_INTERVAL
            self.total_number_of_threads = int(self.total_number_of_threads)
            self.time_wait = int(self.time_wait)

            pool_pool = list()
            size = min(self.total_number_of_threads, len(all_rows))
            loop_count = (len(all_rows) / self.total_number_of_threads)
            concur_looper = int(loop_count) + 1 if int(loop_count) != loop_count else int(loop_count)
            for j in range(concur_looper):
                pool = Pool(processes=size)
                res = pool.map_async(e6x_query_method, (i for i in all_rows[size * j:size * (j + 1)]))
                pool_pool.append(res)
                time.sleep(self.time_wait)
            logger.info("Running concurrent queries in E6DATA with ENABLE_CONCURRENCY enabled")
            for j in pool_pool:
                for output in j.get():
                    status, query_alias_name, query, db_name, client_perceived_time = output[0], output[1], output[2], \
                        output[3], output[4]

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
                        client_perceived_time=client_perceived_time,
                        **status
                    ))
                    logger.info(dict(
                        s_no=self.counter + 1,
                        query_alias_name=query_alias_name,
                        query_text=query,
                        db_name=db_name,
                        client_perceived_time=client_perceived_time,
                        **status
                    ))
                    logger.info('{}. Query status of query alias: {} {}'.format(
                        self.counter,
                        query_alias_name,
                        status.get('query_status'))
                    )
                    self.counter += 1
                    logger.info('JOINING...')
        else:
            for row in all_rows:
                logger.info("Running sequential queries in E6DATA with ENABLE_CONCURRENCY disabled")
                status, query_alias_name, query, db_name, client_perceived_time = e6x_query_method(row)
                err_msg = status.pop('err_msg')
                self.query_results.append(dict(
                    **status,
                    query_alias_name=query_alias_name,
                    query_text=query,
                    db_name=db_name,
                    client_perceived_time=client_perceived_time,
                    err_msg=err_msg
                ))

        logger.info('TIMESTAMP {} ALL Query completed'.format(datetime.datetime.now()))
        self.total_number_of_queries = len(all_rows)
        self.total_number_of_queries_successful = self.success_query_count
        self.total_number_of_queries_failed = self.failed_query_count

        logger.info('Total failed query: {}'.format(self.failed_query_count))
        logger.info('Total success query: {}'.format(self.success_query_count))
        is_any_query_failed = self.failed_query_count > 0
        return self.query_results, is_any_query_failed


if __name__ == '__main__':
    logger.info('Engin IP is {}'.format(os.getenv("ENGINE_IP")))
    a = threading.Thread(target=ram_cpu_usage, args=(5,))
    a.daemon = True
    a.start()
    E6XBenchmark()
