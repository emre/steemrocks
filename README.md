# steemrocks
Activity feed for steem accounts

##### Installation and Running
```
$ virtualenv -p python3 steemrocks-env
$ source steemrocks-env/bin/activate
$ git clone https://github.com/emre/steemrocks.git
$ cp steemrocks/local_settings.py.ex local_settings.py
$ vim steemrocks/local_settings.py # edit accordingly
$ pip install -r requirements.txt
```

#### Database import

Database creation queries located under the sql directory. Just import it
to your mySQL database.
```
mysql -u username -p database_name < sql/base.sql

```
Installation is done. steemrocks has two seperate processes.

##### Transaction Listener Process
```
$ FLASK_APP=app.py flask listen_transactions
```

This process listens transactions and put them into the database. By default
It will start listening from the latest block. If you want to specify a starting
block, you should edit ~/.steemrocks/checkpoint file (create it, if it does not exists) 
and put the block number here.

You should see something like that:

<img src="https://i.hizliresim.com/Oyo6WP.png">

##### Server Process

In development environment:

```
cd [steemrocks_directory]
FLASK_APP=app.py run
```

For production, you can use gunicorn:

```
/gunicorn steemrocks.app:app --bind 0.0.0.0:[PORT_NUMBER]
```


