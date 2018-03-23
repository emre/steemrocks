from math import ceil

import json
import requests
import pymysql
from flask import g
from steem import Steem
from steem.amount import Amount
from pymongo import MongoClient

from . import settings

_steem_connection = None
_mongo_connection = None


def connect_db():
    conn = pymysql.connect(*settings.DB_INFO, charset='utf8')
    conn.cursorclass = pymysql.cursors.DictCursor
    return conn


def get_db(new=False):
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    if new:
        return connect_db()
    if not hasattr(g, 'mysql_db'):
        g.mysql_db = connect_db()

    return g.mysql_db


def get_steem_conn():
    global _steem_connection
    if not _steem_connection:
        _steem_connection = Steem(nodes=settings.NODES)
    return _steem_connection


def get_mongo_conn():
    global _mongo_connection
    if not _mongo_connection:
        _mongo_connection = MongoClient('mongo1.steemdata.com',
                                        username='steemit',
                                        password='steemit',
                                        authSource='SteemData',
                                        authMechanism='SCRAM-SHA-1')
    return _mongo_connection


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
               (num > self.page - left_current - 1 and
                num < self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num


class Coins(object):

    def request_coins(self, name):
        base = "https://min-api.cryptocompare.com/data/price?fsym="
        compare = "&tsyms=BTC,USD,EUR,ETH,LTC"
        url = base+name+compare
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


def vests_to_sp(vests, info):
    steem_per_mvests = (
        Amount(info["total_vesting_fund_steem"]).amount /
        (Amount(info["total_vesting_shares"]).amount / 1e6)
    )

    return vests / 1e6 * steem_per_mvests


def get_curation_rewards(account, info, checkpoint_val=100):
    total_reward_in_rshares = 0
    total_reward_in_sp = 0
    checkpoint = int(checkpoint_val)
    increase_per_checkpoint = int(checkpoint_val)
    checkpoints = []
    history = account.history(filter_by=["curation_reward"])
    for curation_reward in history:
        curation_reward_rshares = Amount(curation_reward["reward"]).amount
        total_reward_in_rshares += curation_reward_rshares
        total_reward_in_sp += vests_to_sp(curation_reward_rshares, info)
        if int(total_reward_in_sp) % checkpoint < 25 and \
                int(total_reward_in_sp) >= checkpoint:
            checkpoints.append({
                "timestamp": curation_reward["timestamp"],
                "block": curation_reward["block"],
                "sub_total": round(total_reward_in_sp, 2),
            })
            checkpoint += increase_per_checkpoint

    return total_reward_in_sp, total_reward_in_rshares, checkpoints


def hbytes(num):
    for x in ['bytes', 'KB', 'MB', 'GB']:
        if num < 1024.0:
            return "%3.1f%s" % (num, x)
        num /= 1024.0
    return "%3.1f%s" % (num, 'TB')


op_types = [
    "vote",
    "comment",
    "custom_json",
    "transfer",
    "delegate_vesting_shares",
    "claim_reward_balance",
    "account_witness_vote",
    "author_reward",
    "curation_reward",
    "return_vesting_delegation",
    "feed_publish",
    "delete_comment",
    "account_create_with_delegation",
]
