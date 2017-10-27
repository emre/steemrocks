from flask import Flask, render_template, request, redirect, abort

from .tx_listener import listen
from .models import Account
from .utils import get_steem_conn
from .settings import SITE_URL

app = Flask(__name__)


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
    if request.args.get('username'):
        return redirect('/@' + request.args.get('username'))
    return render_template('index.html')


@app.route('/<username>')
@app.route('/@<username>')
def profile(username):
    account = Account(username, get_steem_conn()).set_account_deta()
    if not account.account_data:
        abort(404)

    operations = account.get_operations()
    return render_template(
        'profile.html', account=account,
        operations=operations, site_url=SITE_URL)





