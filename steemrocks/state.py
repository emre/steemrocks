from os.path import expanduser, exists
from os import makedirs
import json

CONFIG_PATH = expanduser('~/.steem_rocks')
STATE = expanduser("%s/state" % CONFIG_PATH)
CHECKPOINT = expanduser("%s/checkpoint" % CONFIG_PATH)


def load_state(fallback_data=None):
    try:
        return json.loads(open(STATE).read())
    except FileNotFoundError as e:
        if not exists(CONFIG_PATH):
            makedirs(CONFIG_PATH)

        dump_state(fallback_data)
        return load_state()


def dump_state(data):
    f = open(STATE, 'w+')
    f.write(json.dumps(data))
    f.close()


def load_checkpoint(fallback_block_num=None):
    try:
        return int(open(CHECKPOINT).read())
    except FileNotFoundError as e:
        if not exists(CONFIG_PATH):
            makedirs(CONFIG_PATH)

        dump_checkpoint(fallback_block_num)
        return load_checkpoint()


def dump_checkpoint(block_num):
    f = open(CHECKPOINT, 'w+')
    f.write(str(block_num))
    f.close()
