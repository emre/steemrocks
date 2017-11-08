from math import ceil

import pymysql
from flask import g
from steem import Steem

from . import settings

_steem_connection = None


def connect_db():
    conn = pymysql.connect(*settings.DB_INFO, charset='utf8')
    conn.cursorclass = pymysql.cursors.DictCursor
    return conn


def get_db():
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    if not hasattr(g, 'mysql_db'):
        g.mysql_db = connect_db()
    return g.mysql_db


def get_steem_conn():
    global _steem_connection
    if not _steem_connection:
        _steem_connection = Steem(nodes=settings.NODES)
    return _steem_connection


class Pagination(object):

    def __init__(self, page, per_page, total_count):
        self.page = page
        self.per_page = per_page
        self.total_count = total_count

    @property
    def pages(self):
        return int(ceil(self.total_count / float(self.per_page)))

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page + 1 < self.pages

    def iter_pages(self, left_edge=2, left_current=2,
                   right_current=5, right_edge=2):
        last = 0
        for num in range(1, self.pages):
            if num <= left_edge or \
               (num > self.page - left_current - 1 and \
                num < self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num