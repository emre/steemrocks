from flask import Flask, render_template, request, redirect, abort, g, url_for

from .tx_listener import listen
from .models import Account
from .utils import get_steem_conn, Pagination
from .settings import SITE_URL

app = Flask(__name__)

PER_PAGE = 40


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
        return redirect('/' + request.args.get('username'))
    return render_template('index.html')


@app.route('/<username>', defaults={'page': 1})
@app.route('/@<username>', defaults={'page': 1})
@app.route('/<username>/page/<int:page>')
@app.route('/@<username>/page/<int:page>')
def profile(username, page):
    account = Account(username, get_steem_conn()).set_account_deta()
    if not account.account_data:
        abort(404)

    start = page * PER_PAGE
    if page == 1:
        start = 0

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
app.jinja_env.globals['url_for_other_page'] = url_for_other_page
