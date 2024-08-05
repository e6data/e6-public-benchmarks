import csv
import datetime
import logging
import time
from multiprocessing import log_to_stderr
import random

import psutil

from utils.envs import QUERY_CSV_COLUMN_NAME, DB_NAME

logger_set = None


def get_logger():
    global logger_set
    if not logger_set:
        logger = log_to_stderr()
        logger.setLevel(logging.INFO)
        logger_set = logger
    return logger_set


def create_readable_name_from_key_name(key: str) -> str:
    """
    :param key: str
    Input: column_name
    Output: Column name
    """
    return " ".join([i.capitalize() for i in key.lower().split("_")])


def read_from_csv(file_path: str, shuffle=False):
    """
    :param file_path: CSV file absolute path.
    :param shuffle: shuffle the data.
    return: List of dict
    """
    with open(file_path, 'r') as fh:
        reader = csv.DictReader(fh)
        csv_data = [i for i in reader]
    if shuffle:
        random.shuffle(csv_data)
    data = list()
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
    return data


def ram_cpu_usage(interval: int):
    """
    To get the current RAM and CPU usage.
    :param interval: CPU percentage interval
    """
    while True:
        mem_usage = psutil.virtual_memory()
        cpu_usage = psutil.cpu_percent(interval)
        get_logger().info(
            f"RAM USAGE: {mem_usage.used / (1024 ** 3):.2f}G CPU USAGE {cpu_usage}%"
        )


if __name__ == '__main__':
    ram_cpu_usage(2)
