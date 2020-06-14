import sqlite3
from os import sys, path
import logging
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#from settings.settings import db_path, case_db, case_table, case_table_ddl, case_table_idx, enrichment_table, enrichment_table_ddl, enrichment_table_idx

#Enable logging
appname = path.basename(__file__)
formatter = logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s', "%b %d %H:%M:%S")
logger = logging.getLogger(appname)
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('{}.log'.format(appname))
fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)
logger.addHandler(fh)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)

class sqlhelper(object):
    def __init__(self, dbname):
        self.dbpath = path.dirname(path.basename(__file__))
        self.dbname = dbname
        if path.isfile('{}{}'.format(self.dbpath, self.dbname)):
            logger.info('Database Found.Connecting to DB:{}'.format(self.dbname))
        else:
            logger.info('Database not found! Creating a new one:{}{}'.format(self.dbpath, self.dbname))
        try:
            self.conn = sqlite3.connect('{}{}'.format(self.dbpath, self.dbname))
            logger.info('Connected to Database:{}'.format(self.dbname))
        except Exception as e:
            logger.error('DB found but failed to connect database.{}-{}'.format(self.dbname, e))
            sys.exit(1)

    def create_table(self, tablename, ddl):
        conn = self.conn
        # #Give the column defs in sqllite format.Exp: sl.create_table('table1', 'id INTEGER PRIMARY KEY, col1 TEXT, col2 TEXT')
        table_ddl = 'CREATE TABLE IF NOT EXISTS {}({});'.format(tablename, ddl)
        if conn is not None:
            try:
                c = conn.cursor()
                c.execute('SELECT 1 FROM {} LIMIT 1'.format(tablename))
                if c.rowcount:
                    logger.info('Table found and connected.:{}'.format(tablename))
            except Exception as e:
                message = e.args[0]
                if message.startswith('no such table'):
                    logger.info('Table does not exist! Creating a new one.:{}'.format(tablename))
                    c = conn.cursor()
                    c.execute(table_ddl)
                else:
                    logger.error('Table exists but tricky things happening at DB!:{}'.format(e))
                    conn.close()
                    sys.exit(1)
        else:
            logger.error('Could not initiate the database during create_table:{}'.format(tablename))

    def run_qry(self, qry):
        conn = self.conn
        # Exp: sl.run_qry("SELECT * from table1")
        if conn is not None:
            c = conn.cursor()
            c.execute("{}".format(qry))
            result = c.fetchall()
            return result
        else:
            logger.error('Could not connect to database during run_sql.')
    
    def get_records_by_val(self, tablename, return_field, where_field, where_value):
        conn = self.conn
        if conn is not None:
            c = conn.cursor()
            c.execute('SELECT {} FROM {} WHERE {} = \"{}\"'.format(return_field, tablename, where_field, where_value))
            result = c.fetchall()
            return result
        else:
            logger.error('Could not connect to database during get_record_columns.')

    def insert_record(self, tablename, cols, vals):
        conn = self.conn
        # #Give the column list/val list in order and format.Exp: sl.insert_record('table1', 'id, col1, col2', '"1","2","3"')
        insert_dml = ('INSERT INTO {} ({}) VALUES ({})'.format(tablename, cols, vals))
        if conn is not None:
            try:
                c = conn.cursor()
                c.execute(insert_dml)
                logger.info('New record inserted to {} successfully.:{}'.format(tablename, vals))
                conn.commit()
            except Exception as e:
                logger.error('Could not insert records to table!:{}-{}'.format(tablename, e))
                conn.rollback()
                sys.exit(1)
        else:
            logger.error('Could not connect to database during new_case_record.')
    
    def update_record(self, tablename, upd_col, upd_val, where_field, where_val):
        conn = self.conn
        # #Give a single column and val to be updated in order and format.Exp: sl.insert_record('table1', 'id, col1, col2', '"1","2","3"')
        update_dml = ('UPDATE {} SET {} = \"{}\" WHERE {} = \"{}\"'.format(tablename, upd_col, upd_val, where_field, where_val))
        if conn is not None:
            c = conn.cursor()
            try:
                c.execute(update_dml)
                conn.commit()
            except BaseException as e:
                logger.error('Couldnt update the record for {} - {} for {} - Error:{}'.format(tablename, upd_col, where_val, e))
                conn.rollback()
                sys.exit(1)
        else:
                logger.error('Could not connect to database during update_record.')

    def check_record(self, tablename, field, val):
        # Checking for ex-records by querying ids.
        conn = self.conn
        result = False
        if conn is not None:
            c = conn.cursor()
            c.execute("SELECT {} FROM {} WHERE {} = {}".format(field, tablename, field, val))
            if c.fetchone() is not None:
                result = True
        else:
            logger.error('Could not connect to database during check_exrecord.')
        return result

# sl = sqlhelper("test.db")
# sl.create_table('table1', 'id INTEGER PRIMARY KEY, col1 TEXT, col2 TEXT')
# sl.insert_record('table1', 'id, col1, col2', '"1","2","3"')
# sl.update_record('table1','col2','4','id','1')
# print(sl.run_qry("SELECT * from table1"))
# print(sl.get_records_by_val('table1','col2','id','1'))
# print(sl.check_record('table1','col2','4'))
# print(sl.check_record('table1','col2','5'))
##connection = sqlite3.connect('./test.db')
##cursor = connection.execute('select * from table1')
##print(cursor.description)
##sl.run_sql("SELECT c.case_id, e.enrichment_id from cases c LEFT OUTER JOIN enrichments e ON c.id = e.id where e.status = 'Open'")
