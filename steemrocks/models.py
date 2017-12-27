import json
import logging
import math
import time
import uuid
from datetime import datetime

from dateutil.parser import parse
from steem.amount import Amount
from steem.blockchain import Blockchain

from . import state
from .settings import INTERFACE_LINK, SITE_URL
from .utils import get_db, get_steem_conn

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
        cursor = self.db_conn.cursor()
        query = "INSERT IGNORE INTO blocks " \
                "(`id`, `timestamp`, `raw_data`, `witness`, `num`) VALUES " \
                "(%s, %s, %s, %s, %s)"

        cursor.execute(
            query, [
                self.id, self.created_at, '{}', self.witness, self.num])

        self.db_conn.commit()
        end = time.time()
        logger.info('Persisting to database took %s seconds.', end - start)


class Transaction(object):
    def __init__(self, db_conn, block_num, tx_id):
        self.db_conn = db_conn
        self.id = tx_id
        self.block_num = block_num
        self.raw_data = '{}'

        if self.id == "0000000000000000000000000000000000000000":
            self.id = "vop-%s" % str(uuid.uuid4())


    def persist(self):
        cursor = self.db_conn.cursor()
        dumped_raw_data = json.dumps(self.raw_data)

        query = "INSERT IGNORE INTO transactions " \
                "(`id`, `block_num`, `raw_data`) VALUES " \
                "(%s, %s, %s)"

        cursor.execute(query, [
            self.id, self.block_num, dumped_raw_data])
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

    @property
    def trx_id(self):
        if self.tx_id.startswith("vop"):
            return "virtual operation"
        return self.tx_id

    def get_concrete_operation(self):
        if self.type == "vote":
            if 'voter' in self.raw_data:
                return Vote(self.raw_data, account=self.account)
            else:
                logger.error(self.raw_data)
        elif self.type == "comment":
            if self.raw_data.get("title") or \
                    self.raw_data.get("parent_author"):
                return Comment(self.raw_data)
            elif self.raw_data.get("author") and self.raw_data.get("permlink"):
                return Comment(self.raw_data)
        elif self.type == "custom_json":
            try:
                raw_data = json.loads(self.raw_data["json"])
            except Exception as e:
                logger.error(self.raw_data["json"])
                return
            if raw_data and len(raw_data) == 2:
                try:
                    return CustomJson(
                        raw_data[0], raw_data[1], account=self.account
                    ).get_concrete_operation()
                except KeyError:
                    return None
            else:
                logger.error(raw_data)
        elif self.type == "transfer":
            return Transfer(
                self.raw_data,
                account=self.account,
            )
        elif self.type == "delegate_vesting_shares":
            return Delegate(
                self.raw_data,
                account=self.account,
            )
        elif self.type == "claim_reward_balance":
            return ClaimRewardBalance(
                self.raw_data,
                account=self.account,
            )
        elif self.type == "producer_reward":
            # this looks spammy on top producers.
            # ignoring it until we find a better solution.
            # return ProducerReward(
            #     self.raw_data,
            #     account=self.account,
            # )
            pass
        elif self.type == "account_witness_vote":
            return AccountWitnessVote(
                self.raw_data,
                account=self.account,
            )
        elif self.type == "author_reward":
            return AuthorReward(
                self.raw_data,
                account=self.account,
            )
        elif self.type == "curation_reward":
            return CurationReward(
                self.raw_data,
                account=self.account,
            )
        elif self.type == "return_vesting_delegation":
            return ReturnVestingDelegation(
                self.raw_data,
                account=self.account
            )
        elif self.type == "feed_publish":
            return FeedPublish(
                self.raw_data,
                account=self.account,
            )
        elif self.type == "delete_comment":
            return DeleteComment(
                self.raw_data,
                account=self.account,
            )
        elif self.type == "account_create_with_delegation":
            return AccountCreateWithDelegation(
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
        self.weight = raw_data["weight"]
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
        return "%s/@%s" % (SITE_URL, self.voter)

    @property
    def exact_action(self):
        if self.weight == 0:
            return "unvoted"
        return "upvoted"

    @property
    def action(self):
        if self.account != self.voter:
            voter_template = '<a href="%s">%s</a>' % (
                self.voter_link, self.voter)
        else:
            voter_template = self.voter

        return '%s %s <a href="%s">%s</a>. <small><i>(%s%%)</i></small>' % (
            voter_template, self.exact_action, self.link,
            self.permlink, self.weight / 100)


class Comment(object):
    def __init__(self, raw_data):
        self.author = raw_data.get("author")
        self.permlink = raw_data.get("permlink")
        self.parent_author = raw_data.get("parent_author")
        self.parent_permlink = raw_data.get("parent_permlink")
        self.title = raw_data.get("title")
        self.body = raw_data.get("body")
        self.json_metadata = raw_data.get("json_metadata")

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
        else:
            return self.link

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
            if 'following' in self.raw_data and 'follower' in self.raw_data:
                return Follow(self.raw_data, account=self.account)
            else:
                logger.error(self.raw_data)
        elif self.type == "reblog":
            return Resteem(self.raw_data, account=self.account)


class Transfer(object):
    def __init__(self, raw_data, account=None):
        self.to = raw_data.get("to")
        self._from = raw_data.get("from")
        self.memo = raw_data.get("memo")
        self.amount = raw_data.get("amount")
        self.account = account

    @property
    def public_memo(self):
        if self.memo.startswith("#"):
            return "Private memo. Contents are hidden."
        return self.memo

    @property
    def action(self):
        from_template = self.actor
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

        elif raw_data["what"] == ["ignore"]:
            self.type = "mute"

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

        exact_action = "followed"
        if self.type == "unfollow":
            exact_action = "unfollowed"
        elif self.type == "mute":
            exact_action = "muted"

        return "%s %s %s." % (
            actor_template, exact_action,
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
        last_vote_time = parse(self.account_data["last_vote_time"])
        diff_in_seconds = (datetime.utcnow() - last_vote_time).seconds
        regenerated_vp = diff_in_seconds * 10000 / 86400 / 5
        total_vp = (
                   self.account_data["voting_power"] + regenerated_vp) / 100
        if total_vp > 100:
            total_vp = 100

        return "%.2f" % total_vp

    @property
    def reputation(self, precision=2):
        rep = int(self.account_data['reputation'])
        if rep == 0:
            return 25
        score = max([math.log10(abs(rep)) - 9, 0]) * 9 + 25
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
        return round(self.sp + self.received_sp - self.delegated_sp, 2)

    @property
    def worth_sp(self):
        s = get_steem_conn()
        b = Blockchain()

        p = 10000
        sp = self.total_sp # steem power
        vp = 100 # voting power
        vw = 100 # voting weight
        tvf = float(b.info()['total_vesting_fund_steem'].replace(" STEEM", ""))
        tvs = float(b.info()['total_vesting_shares'].replace(" VESTS", ""))
        r = float(sp / (tvf / tvs))
        m = float(100 * vp * (100 * vw) / p)
        m = float((m + 49) / 50)
        quote = float(s.get_current_median_history_price()['quote'].replace(" STEEM", ""))
        base = float(s.get_current_median_history_price()['base'].replace(" SBD", ""))
        o = base / quote
        rb = float(s.get_reward_fund('post')['reward_balance'].replace(" STEEM", ""))
        rc = float(s.get_reward_fund('post')['recent_claims'])
        i = rb / rc
        return "%.4f" % (r * m * 100 * i * o)

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

    def get_operation_count(self):
        query = 'SELECT COUNT(*) as total FROM operations where ' \
                'actor=%s or effected=%s'
        cursor = self.db_conn.cursor()
        cursor.execute(query, (self.username, self.username))
        return cursor.fetchone()["total"]

    def get_operations(self, start=0, end=0):
        query = 'SELECT * FROM operations where ' \
                'actor=%s or effected=%s ORDER BY created_at ' \
                'DESC LIMIT %s, %s'

        cursor = self.db_conn.cursor()
        cursor.execute(query, (self.username, self.username, start, end))
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

    @property
    def user_link(self):
        return "%s/@%s" % (INTERFACE_LINK, self.username)

class Delegate:

    def __init__(self, raw_data, account=None):
        self.raw_data = raw_data
        self.account = account
        self.vesting_shares = raw_data["vesting_shares"]

    @property
    def actor(self):
        return self.raw_data["delegator"]

    @property
    def effected(self):
        return self.raw_data["delegatee"]

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

        vesting_shares = int(Amount(self.vesting_shares))
        exact_action = "delegated"
        if vesting_shares == 0:
            return "%s undelegated to %s." % (
                actor_template, effected_template
            )
        return "%s %s %s VESTS to %s" % (
            actor_template, exact_action, vesting_shares, effected_template)


class ClaimRewardBalance:

    def __init__(self, raw_data, account=None):
        self.raw_data = raw_data
        self.account = account

    @property
    def actor(self):
        return self.raw_data["account"]

    @property
    def effected(self):
        return ""

    @property
    def action(self):
        return "%s claimed rewards: %s sbd, %s steem, %.2f vests." % (
            self.actor,
            Amount(self.raw_data["reward_sbd"]),
            Amount(self.raw_data["reward_steem"]),
            Amount(self.raw_data["reward_vests"])
        )


class Resteem:

    def __init__(self, raw_data, account=None):
        self.raw_data = raw_data
        self.account = account

    @property
    def type(self):
        return "resteem"

    @property
    def actor(self):
        return self.raw_data["account"]

    @property
    def effected(self):
        return self.raw_data["author"]

    @property
    def action(self):
        actor_url = SITE_URL + '/' + self.actor
        actor_template = self.actor

        if self.account != self.actor:
            actor_template = '<a href="%s" target="_blank">%s</a>' % (
                actor_url, actor_template)

        return '%s resteemed <a href="%s">%s</a>.' % (
            actor_template, self.link, self.raw_data["permlink"])

    @property
    def link(self):
        return "%s/@%s/%s" % (
            INTERFACE_LINK, self.raw_data["author"], self.raw_data["permlink"])


class ProducerReward:

    def __init__(self, raw_data, account=None):
        self.raw_data = raw_data
        self.account = account
        self.vesting_shares = Amount(raw_data["vesting_shares"])

    @property
    def actor(self):
        return self.raw_data["producer"]

    @property
    def effected(self):
        return ""

    @property
    def action(self):
        return "%s got producer rewards: %.2f vests." % (
            self.actor, self.vesting_shares)


class AuthorReward:

    def __init__(self, raw_data, account=None):
        self.raw_data = raw_data
        self.account = account

    @property
    def actor(self):
        return self.raw_data["author"]

    @property
    def effected(self):
        return ""

    @property
    def link(self):
        return "%s/@%s/%s" % (
            INTERFACE_LINK, self.raw_data["author"], self.raw_data["permlink"])

    @property
    def exact_action(self):
        return "author rewards"

    @property
    def action(self):
        return '%s got %s for <a href="%s">%s</a>. ' \
               '<br>%s sbd, %s steem, %.2f vests.' % (
                self.actor,
                self.exact_action,
                self.link,
                self.raw_data["permlink"][0:8],
                Amount(self.raw_data["sbd_payout"]).amount,
                Amount(self.raw_data["steem_payout"]).amount,
                Amount(self.raw_data["vesting_payout"]).amount,
        )


class CommentReward(AuthorReward):

    @property
    def exact_action(self):
        return "comment rewards"


class FeedPublish:

    def __init__(self, raw_data, account=None):
        self.raw_data = raw_data
        self.account = account

    @property
    def actor(self):
        return self.raw_data["publisher"]

    @property
    def effected(self):
        return ""

    @property
    def action(self):
        return "%s published price feed. $%s." % (
            self.actor, Amount(self.raw_data["exchange_rate"]["base"]).amount)


class AccountWitnessVote:

    def __init__(self, raw_data, account=None):
        self.raw_data = raw_data
        self.account = account

    @property
    def actor(self):
        return self.raw_data["account"]

    @property
    def effected(self):
        return self.raw_data["witness"]

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

        exact_action = "approved" if self.raw_data["approve"] else "unapproved"

        return "%s %s witness: %s." % (
            actor_template, exact_action, effected_template
        )


class DeleteComment:

    def __init__(self, raw_data, account=None):
        self.raw_data = raw_data
        self.account = account

    @property
    def actor(self):
        return self.raw_data["author"]

    @property
    def effected(self):
        return ""

    @property
    def action(self):
        return "%s deleted comment. (@%s)" % (
            self.actor, self.raw_data["permlink"])


class AccountCreateWithDelegation:

    def __init__(self, raw_data, account=None):
        self.raw_data = raw_data
        self.account = account

    @property
    def actor(self):
        return self.raw_data["creator"]

    @property
    def effected(self):
        return self.raw_data["new_account_name"]

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

        return "%s created account %s." % (actor_template, effected_template)


class CurationReward:

    def __init__(self, raw_data, account=None):
        self.raw_data = raw_data
        self.account = account

    @property
    def actor(self):
        return self.raw_data["curator"]

    @property
    def effected(self):
        return ""

    @property
    def link(self):
        return "%s/@%s/%s" % (
            INTERFACE_LINK,
            self.raw_data["comment_author"],
            self.raw_data["comment_permlink"])

    @property
    def action(self):
        link = '<a href="%s">%s</a>' % (
            self.raw_data["comment_permlink"],
            self.raw_data["comment_permlink"])
        return "%s got curation reward: %s for %s" % (
            self.actor,
            self.raw_data["reward"].lower(),
            link
        )


class ReturnVestingDelegation:

    def __init__(self, raw_data, account=None):
        self.raw_data = raw_data
        self.account = account

    @property
    def actor(self):
        return self.raw_data["account"]

    @property
    def effected(self):
        return ""

    @property
    def action(self):
        return "%s got vesting delegations back. %.2f vests." % (
            self.actor,
            Amount(self.raw_data["vesting_shares"]).amount
        )
