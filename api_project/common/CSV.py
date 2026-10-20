#! /usr/bin/env python
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@gmail.com
createTime  : 2024/11/21 1:09
fileName    : CSV.py
'''

import os.path
from csv import reader, writer

def Reader(file_path: str, ignore_first_row: bool = True):
    '''
    CSV文件的读取函数
    :param file_path:
    :param ignore_first_row:
    :return:
    实例:
    print(Reader(file_path='../case_data_files/api.csv', ignore_first_row=True))
    '''
    return list(reader(open(file_path, 'r', encoding='utf-8')))[1:] if ignore_first_row else \
        list(reader(open(file_path, 'r', encoding='utf-8')))

def Writer(file_path: str = '', data: list[list] = None, ignore_first_row: bool = False):
    '''
    CSV文件的写入函数
    :param file_path:
    :param data:
    :param ignore_first_row:
    :return:
    实例:
    Writer(file_path='../case_data_file/接口名称.csv',
           data=[
             ['method', 'uri', 'headers', 'data'],
             ['GET', '/login', {'content-type': 'application/json'}, {'id':5}]
           ],
           ignore_first_row=True)

    '''
    data = data[1:] if ignore_first_row else data
    mode = 'a' # if ignore_first_row else 'w'
    if os.path.isfile(file_path):
        alllines = Reader(file_path, ignore_first_row=False)
    else:
        alllines = []
    for line in data:
        if line not in alllines:
            writer(open(file_path, mode, encoding='utf-8', newline='')).writerow(line)  # .writerows(data)