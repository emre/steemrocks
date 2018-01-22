import logging

from .utils import get_db

logger = logging.getLogger('steemrocks')
logger.setLevel(logging.INFO)
logging.basicConfig()


def gc():
    db = get_db()
    cursor = db.cursor()
    query = "SELECT MIN(id) AS minimum_id FROM operations";
    cursor.execute(query)
    min_id = cursor.fetchone()["minimum_id"]

    query = "SELECT MAX(id) AS maximum_id FROM operations";
    cursor.execute(query)
    max_id = cursor.fetchone()["maximum_id"]

    to = max_id - 100000
    for i in range(min_id, to):
        cursor.execute("DELETE FROM operations WHERE id = %s", i)
        db.commit()
        print("deleted", i)






