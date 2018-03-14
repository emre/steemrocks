import logging
import time
import concurrent
import multiprocessing

from . import models, state
from .utils import get_db, get_steem_conn

logger = logging.getLogger('steemrocks')
logger.setLevel(logging.INFO)
logging.basicConfig()


class TransactionListener(object):

    def __init__(self, steem):
        self.steem = steem
        self.db = get_db()
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=8)

    @property
    def properties(self):
        props = self.steem.get_dynamic_global_properties()
        if not props:
            logger.info('Couldnt get block num. Retrying.')
            return self.properties
        return props

    @property
    def last_block_num(self):
        return self.properties['head_block_number']

    @property
    def block_interval(self):
        config = self.steem.get_config()
        return config["STEEMIT_BLOCK_INTERVAL"]

    def process_block(self, block_num, retry_count=0):
        block_data = self.steem.get_block(block_num)

        if not block_data:
            if retry_count > 3:
                logger.error(
                    'Retried 3 times to get this block: %s Skipping.',
                    block_num
                )
                return

            logger.error(
                'Couldnt read the block: %s. Retrying.', block_num)
            self.process_block(block_num, retry_count=retry_count + 1)

        logger.info('Processing block: %s', block_num)
        if 'transactions' not in block_data:
            return

        self.persist_block(block_data, block_num)
        state.dump_state(self.properties)

    def run(self, start_from=None):
        if start_from is None:
            last_block = state.load_checkpoint(
                fallback_block_num=self.last_block_num,
            )
            logger.info('Last processed block: %s', last_block)
        else:
            last_block = start_from
        while True:

            while (self.last_block_num - last_block) > 0:
                last_block += 1
                self.process_block(last_block)
                state.dump_checkpoint(last_block)

            # Sleep for one block
            block_interval = self.block_interval
            logger.info('Sleeping for %s seconds.', block_interval)
            time.sleep(block_interval)

    def persist_block(self, block_data, block_num):
        db = get_db(new=True)

        block = models.Block(db, block_num, block_data)
        self.thread_pool.submit(block.persist)
        saved_txs = set()
        operation_data = self.steem.get_ops_in_block(
            block_num, virtual_only=False)

        for operation in operation_data:
            if operation["trx_id"] not in saved_txs:
                transaction = models.Transaction(
                    db, block_num, operation["trx_id"])
                self.thread_pool.submit(transaction.persist)
                saved_txs.add(operation["trx_id"])

            op_type, op_value = operation['op'][0:2]

            _operation = models.Operation(
                db, transaction.id,
                op_type, op_value,
                block.created_at)

            if _operation.sub_operation:
                self.thread_pool.submit(_operation.persist)


def listen():
    logger.info('Starting Transaction Listener')
    steem = get_steem_conn()
    tx_listener = TransactionListener(steem)
    tx_listener.run()

