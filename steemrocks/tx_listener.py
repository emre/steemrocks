import concurrent.futures
import logging
import time

from . import models, state
from .utils import get_db_conn, get_steem_conn

logger = logging.getLogger('steemrocks')
logger.setLevel(logging.DEBUG)
logging.basicConfig()


class TransactionListener(object):

    def __init__(self, steem):
        self.steem = steem
        self.db = get_db_conn()

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

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.persist_block, block_data, block_num)
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
        block = models.Block(self.db, block_num, block_data)
        block.persist()

        for transaction_id in block_data.get("transaction_ids"):
            tx_data = self.steem.get_transaction(transaction_id)
            transaction = models.Transaction(self.db, block_num, tx_data)
            transaction.persist()

            for operation_data in transaction.raw_data.get("operations", []):
                op_type, op_value = operation_data[0:2]
                operation = models.Operation(
                    self.db, transaction.id,
                    op_type, op_value,
                    block.created_at)
                operation.persist()


def listen():
    logger.info('Starting Transaction Listener')
    steem = get_steem_conn()
    tx_listener = TransactionListener(steem)
    tx_listener.run()

