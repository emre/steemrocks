import pymysql
from flask import g
from steem import Steem

from . import settings

_steem_connection = None


def connect_db():
    conn = pymysql.connect(*settings.DB_INFO)
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
