from . import settings
from steem import Steem
import pymysql


_db_connection = None
_steem_connection = None


def get_db_conn():
    global _db_connection
    if not _db_connection:
        _db_connection = pymysql.connect(*settings.DB_INFO)
        _db_connection.cursorclass = pymysql.cursors.DictCursor
    return _db_connection


def get_steem_conn():
    global _steem_connection
    if not _steem_connection:
        _steem_connection = Steem(
            keys=[settings.PRIVATE_POSTING_KEY], nodes=settings.NODES)
    return _steem_connection
