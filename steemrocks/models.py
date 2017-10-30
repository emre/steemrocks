import json
import logging
import math
import time
from dateutil.parser import parse
from steem.amount import Amount

from . import state
from .utils import get_db
from .settings import INTERFACE_LINK, SITE_URL

logger = logging.getLogger('steemrocks')
logger.setLevel(logging.DEBUG)
logging.basicConfig()


class Block(object):
    def __init__(self, db_conn, block_num, block_data):
        self.db_conn = db_conn
        self.id = block_data.get("block_id")
        self.num = block_num
        self.timestamp = block_data.get("timestamp")
        self.witness = block_data.get("witness")
        self.raw_data = block_data
        self.transactions = block_data.get("transactions")
        self.created_at = parse(self.raw_data['timestamp'])

    def get_from_db(self, block_id):
        pass

    def persist(self):
        start = time.time()
        dumped_raw_data = json.dumps(self.raw_data)
        cursor = self.db_conn.cursor()
        query = "INSERT INTO blocks " \
                "(`id`, `timestamp`, `raw_data`, `witness`, `num`) VALUES " \
                "(%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE raw_data=%s"

        cursor.execute(
            query, [
                self.id, self.created_at, dumped_raw_data,
                self.witness, self.num, dumped_raw_data])

        self.db_conn.commit()
        end = time.time()
        logger.info('Persisting to database took %s seconds.', end - start )


class Transaction(object):

    def __init__(self, db_conn, block_num, transaction_data):
        self.db_conn = db_conn
        self.id = transaction_data.get("transaction_id")
        self.block_num = block_num
        self.raw_data = transaction_data

    def persist(self):
        cursor = self.db_conn.cursor()
        dumped_raw_data = json.dumps(self.raw_data)
        query = "INSERT INTO transactions " \
                "(`id`, `block_num`, `raw_data`) VALUES " \
                "(%s, %s, %s) ON DUPLICATE KEY UPDATE raw_data=%s"
        cursor.execute(query, [
            self.id, self.block_num, dumped_raw_data, dumped_raw_data])
        self.db_conn.commit()


class Operation(object):
    def __init__(self, db_conn, tx_id, op_type, op_data, created_at,
                 actor=None, effected=None, account=None):
        self.db_conn = db_conn
        self.tx_id = tx_id
        self.raw_data = op_data
        self.type = op_type
        self.created_at = created_at
        self.actor = actor
        self.effected = effected
        self.account = account

        if isinstance(self.raw_data, str):
            self.raw_data = json.loads(self.raw_data)

    @property
    def sub_operation(self):
        return self.get_concrete_operation()

    def get_concrete_operation(self):
        if self.type == "vote":
            return Vote(self.raw_data, account=self.account)
        elif self.type == "comment":
            if self.raw_data.get("title") or \
                    self.raw_data.get("parent_author"):
                return Comment(self.raw_data)
        elif self.type == "custom_json":
            raw_data = json.loads(self.raw_data["json"])
            return CustomJson(
                raw_data[0], raw_data[1], account=self.account
            ).get_concrete_operation()
        elif self.type == "transfer":
            return Transfer(
                self.raw_data,
                account=self.account,
            )

    def persist(self):
        concrete_operation = self.get_concrete_operation()
        actor, effected = None, None
        if concrete_operation:
            actor = concrete_operation.actor
            effected = concrete_operation.effected

        cursor = self.db_conn.cursor()
        dumped_raw_data = json.dumps(self.raw_data)
        query = "INSERT INTO operations " \
                "(`tx_id`, `type`, `raw_data`, `actor`, `effected`, " \
                "`created_at`) VALUES " \
                "(%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE raw_data=%s"
        cursor.execute(query, [
            self.tx_id, self.type, dumped_raw_data, actor, effected,
            self.created_at, dumped_raw_data])
        self.db_conn.commit()


class Vote(object):

    def __init__(self, raw_data, account=None):
        self.voter = raw_data["voter"]
        self.author = raw_data["author"]
        self.permlink = raw_data["permlink"]
        self.account = account

    @property
    def actor(self):
        return self.voter

    @property
    def effected(self):
        return self.author

    @property
    def link(self):
        return "%s/@%s/%s" % (INTERFACE_LINK, self.author, self.permlink)

    @property
    def voter_link(self):
        return "%s/@%s" % (INTERFACE_LINK, self.voter)

    @property
    def action(self):
        if self.account != self.voter:
            voter_template = '<a href="%s">%s</a>' % (
                self.voter_link, self.voter)
        else:
            voter_template = '<strong>%s</strong>' % self.voter

        return '%s upvoted <a href="%s">%s</a>' % (
            voter_template, self.link, self.permlink)


class Comment(object):

    def __init__(self, raw_data):
        self.author = raw_data["author"]
        self.permlink = raw_data["permlink"]
        self.parent_author = raw_data["parent_author"]
        self.parent_permlink = raw_data["parent_permlink"]
        self.title = raw_data["title"]
        self.body = raw_data["body"]
        self.json_metadata = raw_data["json_metadata"]


    @property
    def actor(self):
        return self.author

    @property
    def effected(self):
        return self.parent_author

    @property
    def parent_link(self):
        if self.parent_permlink and self.parent_author:
            return "%s/@%s/%s" % (
                INTERFACE_LINK, self.parent_author, self.parent_permlink)
        return "#"

    @property
    def is_a_post(self):
        return self.parent_author == ""

    @property
    def is_a_comment(self):
        return not self.is_a_post

    @property
    def link(self):
        if self.permlink:
            return "%s/@%s/%s" % (
                INTERFACE_LINK, self.author, self.permlink)


class CustomJson(object):

    def __init__(self, json_type, json_data, account=None):
        self.raw_data = json_data
        self.type = json_type
        self.account = account

    @property
    def sub_operation(self):
        return self.get_concrete_operation()

    def get_concrete_operation(self):
        if self.type == "follow":
            # ugly hack until I figure out what's happening
            if 'following' in self.raw_data and 'follower' in self.raw_data:
                return Follow(self.raw_data, account=self.account)
            else:
                logger.error(self.raw_data)


class Transfer(object):

    def __init__(self, raw_data, account=None):
        self.to = raw_data.get("to")
        self._from = raw_data.get("from")
        self.memo = raw_data.get("memo")
        self.amount = raw_data.get("amount")
        self.account = account

    @property
    def action(self):
        from_template = "<strong>%s</strong>" % self.actor
        if self.account != self._from:
            from_template = '<a href="%s">%s</a>' % (
                '%s/@%s' % (SITE_URL, self._from), self._from
            )
        to_template = "%s" % self.effected
        if self.account != self.to:
            to_template = '<a href="%s">%s</a>' % (
                '%s/@%s' % (SITE_URL, self.to), self.to
            )

        return "%s transferred %s to %s." % (
            from_template,
            self.amount,
            to_template,
        )

    @property
    def actor(self):
        return self._from

    @property
    def effected(self):
        return self.to


class Follow(object):

    def __init__(self, raw_data, account=None):
        self.follower = raw_data["follower"]
        self.following = raw_data["following"]
        self.type = "follow"
        self.raw_data = raw_data
        self.account = account

        if len(raw_data["what"]) == 0:
            self.type = "unfollow"

    @property
    def actor(self):
        return self.follower

    @property
    def effected(self):
        return self.following

    @property
    def action(self):
        actor_url = SITE_URL + '/' + self.actor
        effected_url = SITE_URL + '/' + self.effected
        actor_template = self.actor
        effected_template = self.effected

        if self.account == self.effected:
            actor_template = '<a href="%s" target="_blank">%s</a>' % (
                actor_url, self.actor)
        elif self.account == self.actor:
            effected_template = '<a href="%s" target="_blank">%s</a>' % (
                effected_url, self.effected)

        return "%s %sfollowed %s." % (
            actor_template, "un" if self.type == "unfollow" else "",
            effected_template
        )


class Account:

    def __init__(self, username, steem, db_conn=None):
        self.username = username
        self.steem = steem
        self.account_data = None
        self.json_metadata = None
        self.db_conn = db_conn or get_db()

    def set_account_deta(self):
        self.account_data = self.steem.get_account(self.username)
        if self.account_data and self.account_data.get("json_metadata"):
            self.json_metadata = json.loads(self.account_data['json_metadata'])
        return self

    @property
    def profile(self):
        if self.json_metadata and 'profile' in self.json_metadata:
            return self.json_metadata['profile']

    @property
    def avatar(self):
        if self.profile and 'profile_image' in self.profile:
            return self.profile['profile_image']

        return "https://api.adorable.io/avatars/100/%s.png" % self.username

    @property
    def avatar_small(self):
        if self.profile and 'profile_image' in self.profile:
            return self.profile['profile_image']

        return "https://api.adorable.io/avatars/38/%s.png" % self.username

    @property
    def about(self):
        if self.profile and 'about' in self.profile:
            return self.profile['about']

    @property
    def location(self):
        if self.profile and 'location' in self.profile:
            return self.profile['location']

    @property
    def balances(self):
        steem_balance = "%.3f" % Amount(self.account_data['balance']).amount
        sbd_balance = "%.3f" % Amount(self.account_data['sbd_balance']).amount
        vests = "%.3f" % Amount(self.account_data['vesting_shares']).amount

        return {
            'STEEM': steem_balance,
            'SBD': sbd_balance,
            'VESTS': vests,
        }

    @property
    def voting_power(self):
        return self.account_data['voting_power'] / 100

    @property
    def reputation(self, precision=2):
        rep = int(self.account_data['reputation'])
        if rep == 0:
            return 25
        score = (math.log10(abs(rep)) - 9) * 9 + 25
        if rep < 0:
            score = 50 - score
        return round(score, precision)

    @property
    def sp(self):
        vests = Amount(self.account_data['vesting_shares']).amount
        return round(self.vests_to_sp(vests), 2)

    @property
    def delegated_sp(self):
        vests = Amount(self.account_data['delegated_vesting_shares']).amount
        return round(self.vests_to_sp(vests), 2)

    @property
    def received_sp(self):
        vests = Amount(self.account_data['received_vesting_shares']).amount
        return round(self.vests_to_sp(vests), 2)

    @property
    def total_sp(self):
        return int(self.sp + self.received_sp - self.delegated_sp)

    @property
    def creation_date(self):
        return parse(self.account_data['created']).date()

    def vests_to_sp(self, vests):
        return vests / 1e6 * self.steem_per_mvests()

    def steem_per_mvests(self):
        info = state.load_state()
        return (
            Amount(info["total_vesting_fund_steem"]).amount /
            (Amount(info["total_vesting_shares"]).amount / 1e6)
        )

    def get_operations(self, start=0, end=0):
        query = 'SELECT * FROM operations where ' \
                'actor=%s or effected=%s ORDER BY created_at DESC LIMIT 100'

        cursor = self.db_conn.cursor()
        cursor.execute(query, (self.username, self.username))
        operations = []
        for op in cursor:
            operations.append(Operation(
                self.db_conn,
                op["tx_id"],
                op["type"],
                op["raw_data"],
                op["created_at"],
                actor=op["actor"],
                effected=op["effected"],
                account=self.username
            ))

        return operations
