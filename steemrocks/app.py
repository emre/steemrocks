from flask import Flask, render_template, request, redirect, abort, g, url_for

from .tx_listener import listen
from .garbage_collector import gc
from .models import Account
from steem.account import Account as SteemAccount
from steem.amount import Amount
from .utils import (
    get_steem_conn, Pagination, vests_to_sp, get_curation_rewards,
    get_mongo_conn, op_types
)
from .settings import SITE_URL
from . import state
from dateutil.parser import parse
from datetime import datetime, timedelta
from time import time

import bleach
import requests

app = Flask(__name__)

PER_PAGE = 30


@app.cli.command()
def listen_transactions():
    """
    This command starts listening transactions on the network and saves them\
    into the database.
    $ flask listen_transactions
    """
    listen()


@app.cli.command()
def garbage_collector():
    """
    This command starts listening transactions on the network and saves them\
    into the database.
    $ flask listen_transactions
    """
    gc()


@app.route('/')
def index():
    if request.query_string and request.args.get('account'):
        return redirect('/' + request.args.get('account'))
    return render_template('index.html')


@app.route('/<username>/rewards')
@app.route('/@<username>/rewards')
def rewards(username):
    s = get_steem_conn()
    account = Account(username, get_steem_conn()).set_account_deta()
    if not account.account_data:
        abort(404)

    posts = s.get_discussions_by_blog({"limit": 50, "tag": username})
    comments = s.get_discussions_by_comments(
        {"limit": 100, "start_author": username})

    posts_waiting_cashout = []
    for post in posts + comments:
        cashout_time = parse(post["cashout_time"])

        if cashout_time < datetime.utcnow():
            continue

        if float(post["net_rshares"]) <= 0:
            continue

        if post["author"] != username:
            continue

        posts_waiting_cashout.append(post)

    posts_as_str = ",".join(
        ["@%s/%s" % (p["author"],
                     p["permlink"]) for p in posts_waiting_cashout])

    print(posts_as_str)
    if posts_as_str:

        import time as za
        start = za.time()
        r = requests.post("http://estimator.steem.rocks/rewards.json",
                          data={"links": posts_as_str})
        end = za.time()
        print(end - start)

        rewards = r.json()["rewards"]

        total_author_rewards = round(
            sum(r["author"] for r in rewards), 2)

        total_sbd = round(
            sum(r["sbd_amount"] for r in rewards), 2)

        total_sp = round(
            sum(r["sp_amount"] for r in rewards), 2)

        total_usd = int(round(
            sum(r["usd_amount"] for r in rewards), 0))
    else:
        rewards = []
        total_author_rewards = 0
        total_sbd = 0
        total_sp = 0
        total_usd = 0

    rewards_fixed = []
    for reward in rewards:
        cashout_time = parse(reward["cashout_time"]).timestamp()
        diff = (cashout_time - time()) / 3600
        if diff < 1:
            diff = diff * 60
            until_text = "in %s mins" % int(diff)
        elif diff > 24:
            diff = diff / 24
            until_text = "in %s days" % int(diff)
        else:
            until_text = "in %s hours" % int(diff)

        reward["until"] = until_text
        rewards_fixed.append(reward)

    return render_template(
        "rewards.html",
        account=account,
        rewards=rewards_fixed,
        total_author_rewards=total_author_rewards,
        total_sbd=total_sbd,
        total_sp=total_sp,
        total_usd=total_usd,
    )


@app.route('/<username>', defaults={'page': 1})
@app.route('/<username>/page/<int:page>')
def profile(username, page):
    if username.startswith("@"):
        username = username.replace("@", "")

    op_type = None
    if request.query_string and request.args.get('op_type'):
        op_type = request.args.get("op_type")
        if op_type not in op_types:
            op_type = None

    account = Account(username, get_steem_conn()).set_account_deta()
    if not account.account_data:
        abort(404)

    page = page - 1
    start = page * PER_PAGE
    pagination = Pagination(page, PER_PAGE,
                            account.get_operation_count(op_type=op_type))

    operations = account.get_operations(start=start, end=PER_PAGE,
                                        op_type=op_type)

    return render_template(
        'profile.html', account=account,
        operations=operations,
        site_url=SITE_URL, pagination=pagination,
        op_type=op_type, op_types=op_types)


@app.route('/<username>/curation_rewards')
@app.route('/@<username>/curation_rewards')
def curation_rewards(username):
    if username.startswith("@"):
        username = username.replace("@", "")
    s = get_steem_conn()
    account = Account(username, s).set_account_deta()
    info = s.get_dynamic_global_properties()
    checkpoint_val = request.args.get("checkpoint")
    total_sp, total_rshares, checkpoints = get_curation_rewards(
        SteemAccount(username, steemd_instance=s),
        info,
        checkpoint_val=checkpoint_val)
    return render_template(
        "curation_rewards.html",
        account=account,
        total_sp=round(total_sp, 2),
        total_rshares=total_rshares,
        checkpoints=checkpoints,
    )


@app.route('/<username>/delegations/out')
@app.route('/@<username>/delegations/out')
def delegations(username):
    if username.startswith("@"):
        username = username.replace("@", "")
    s = get_steem_conn()
    account = Account(username, s).set_account_deta()

    outgoing_delegations = s.get_vesting_delegations(username, 0, 100)
    eight_days_ago = datetime.utcnow() - timedelta(days=8)
    expiring_delegations = s.get_expiring_vesting_delegations(
        username,
        eight_days_ago.strftime("%Y-%m-%dT%H:%M:%S"),
        1000
    )
    info = state.load_state()
    outgoing_delegations_fixed = []
    for outgoing_delegation in outgoing_delegations:
        created_at = parse(outgoing_delegation["min_delegation_time"])
        amount = Amount(outgoing_delegation["vesting_shares"]).amount
        outgoing_delegation.update({
            "min_delegation_time": created_at,
            "sp": round(vests_to_sp(amount, info), 2),
            "vesting_shares": round(amount / 1e6, 4),
        })
        outgoing_delegations_fixed.append(outgoing_delegation)

    expiring_delegations_fixed = []
    for expiring_delegation in expiring_delegations:
        created_at = parse(expiring_delegation["expiration"])
        amount = Amount(expiring_delegation["vesting_shares"]).amount
        expiring_delegation.update({
            "expiration": created_at,
            "sp": round(vests_to_sp(amount, info), 2),
            "vesting_shares": round(amount / 1e6, 4),
        })
        expiring_delegations_fixed.append(expiring_delegation)

    return render_template(
        "delegations.html",
        account=account,
        outgoing_delegations=outgoing_delegations_fixed,
        expiring_delegations=expiring_delegations,
    )


@app.route('/<username>/delegations/in')
@app.route('/@<username>/delegations/in')
def incoming_delegations(username):
    if username.startswith("@"):
        username = username.replace("@", "")
    s = get_steem_conn()
    mongo_conn = get_mongo_conn()

    account = Account(username, s).set_account_deta()
    collection = mongo_conn["SteemData"]["Operations"]
    info = state.load_state()

    operations = list(collection.find({
        "type": "delegate_vesting_shares",
        "delegatee": username,
    }).sort("timestamp"))

    delegation_map = {}
    for delegation in operations:
        delegation_map.update(
            {delegation["delegator"]: delegation["vesting_shares"]["amount"]})

    delegation_map = {k: float(v)
                      for k, v in delegation_map.items() if float(v) > 0}

    incoming_delegations = []
    for from_account, vests in delegation_map.items():
        incoming_delegations.append({
            "from": from_account,
            "sp": round(vests_to_sp(vests, info), 2),
            "vesting_shares":  round(vests / 1e6, 4),
        })

    return render_template(
        "incoming_delegations.html",
        incoming_delegations=incoming_delegations,
        account=account,
    )


@app.route('/<username>/bandwidth')
@app.route('/@<username>/bandwidth')
def bandwidth(username):
    if username.startswith("@"):
        username = username.replace("@", "")
    s = get_steem_conn()

    account = Account(username, s).set_account_deta()
    return render_template("bandwidth.html", account=account)


@app.teardown_appcontext
def close_db(error):
    """Closes the database again at the end of the request."""
    if hasattr(g, 'mysql_db'):
        g.mysql_db.close()


def url_for_other_page(page):
    args = request.view_args.copy()
    args['page'] = page
    return url_for(request.endpoint, **args)


def strip_tags(text):
    return bleach.clean(text, tags=["strong", "a", "i", "small", "br"])

app.jinja_env.globals['url_for_other_page'] = url_for_other_page
app.jinja_env.globals['clean'] = strip_tags
