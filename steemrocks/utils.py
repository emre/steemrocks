from math import ceil

import json
import requests
import pymysql
from flask import g
from steem import Steem
from steem.amount import Amount

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
        self.page = page + 1
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
        return self.page < self.pages

    def iter_pages(self, left_edge=2, left_current=2,
                   right_current=5, right_edge=2):
        last = 0
        for num in range(1, self.pages + 1):
            if num <= left_edge or \
               (num > self.page - left_current - 1 and \
                num < self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num

class Coins(object):

    def request_coins(self, name):
        url="http://coincap.io/page/"+name
        c = (requests.get(url)).text
        return json.loads(c)

    def get_coin_price(self, name, price):
        if name == "STEEM":
            prices = self.request_coins("STEEM")
        elif name == "SBD":
            prices = self.request_coins("SBD")

        return "%.5f" % prices[price]

def get_payout_from_rshares(rshares, reward_balance,
                            recent_claims, base_price):
    fund_per_share = Amount(reward_balance).amount / float(recent_claims)
    payout = float(rshares) * fund_per_share * Amount(base_price).amount

    return payout
