from flask import Flask, render_template, request, redirect, abort, g, url_for

from .tx_listener import listen
from .models import Account
from .utils import get_steem_conn, Pagination, Coins
from .settings import SITE_URL
from dateutil.parser import parse
from datetime import datetime

import bleach
import requests

app = Flask(__name__)

PER_PAGE = 25


@app.cli.command()
def listen_transactions():
    """
    This command starts listening transactions on the network and saves them\
    into the database.
    $ flask listen_transactions
    """
    listen()


@app.route('/')
def index():
    coins = Coins()
    if request.query_string and request.args.get('account'):
        return redirect('/' + request.args.get('account'))
    return render_template('index.html', coins=coins)


@app.route('/<username>/rewards')
@app.route('/@<username>/rewards')
def rewards(username):
    s = get_steem_conn()
    account = Account(username, get_steem_conn()).set_account_deta()
    if not account.account_data:
        abort(404)

    posts = s.get_discussions_by_blog({"limit": 50, "tag": username})
    comments = s.get_discussions_by_comments(
        {"limit": 50, "start_author": username})

    posts_waiting_cashout = []
    for post in posts + comments:
        cashout_time = parse(post["cashout_time"])

        if cashout_time < datetime.utcnow():
            continue

        if float(post["net_rshares"]) <= 0:
            continue

        if post["author"] != username:
            print(post["permlink"], '??')

            continue

        posts_waiting_cashout.append(post)

    posts_as_str = ",".join(
        ["@%s/%s" % (p["author"],
                     p["permlink"]) for p in posts_waiting_cashout])

    if posts_as_str:

        r = requests.post("http://estimator.steem.rocks/rewards.json",
                          data={"links": posts_as_str})

        rewards = r.json()["rewards"]

        total_author_rewards = round(
            sum(r["author"] for r in rewards), 2)

        total_sbd = round(
            sum(r["sbd_amount"] for r in rewards), 2)

        total_sp = round(
            sum(r["sp_amount"] for r in rewards), 2)
    else:
        rewards = []
        total_author_rewards = 0
        total_sbd = 0
        total_sp = 0

    return render_template(
        "rewards.html",
        account=account,
        rewards=rewards,
        total_author_rewards=total_author_rewards,
        total_sbd=total_sbd,
        total_sp=total_sp,
    )


@app.route('/<username>', defaults={'page': 1})
@app.route('/<username>/page/<int:page>')
def profile(username, page):
    if username.startswith("@"):
        username = username.replace("@", "")
    account = Account(username, get_steem_conn()).set_account_deta()
    if not account.account_data:
        abort(404)

    page = page - 1
    start = page * PER_PAGE
    pagination = Pagination(page, PER_PAGE, account.get_operation_count())

    operations = account.get_operations(start=start, end=PER_PAGE)

    return render_template(
        'profile.html', account=account,
        operations=operations, site_url=SITE_URL, pagination=pagination)


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
