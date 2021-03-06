from sqlalchemy import create_engine, Column, Integer, String, DateTime, Date, Text
from sqlalchemy.schema import CreateSchema
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import ProgrammingError, IntegrityError
from scraper_lib import raw_config

Base = declarative_base()

SCHEMA = 'existentialcomics'
# Used when schema cannot be used
table_prefix = ''

if not raw_config.get('database', 'uri').startswith('postgres'):
    table_prefix = SCHEMA + '_'
    SCHEMA = None


class Comic(Base):
    __tablename__ = table_prefix + 'comic'
    __table_args__ = {'schema': SCHEMA}
    id = Column(Integer, primary_key=True, autoincrement=True)
    time_collected = Column(DateTime)
    comic_id = Column(Integer)
    title = Column(String(1024))
    philosophers = Column(String(2048))  # Will be delimited by `,`
    num_philosophers = Column(Integer)
    alt = Column(Text)
    ocr = Column(Text)
    explanation = Column(Text)  # Will be delimited by `|`
    file_paths = Column(Text)
    num_panels = Column(Integer)  # Number of images that are in `file_paths`


class Setting(Base):
    __tablename__ = table_prefix + 'setting'
    __table_args__ = {'schema': SCHEMA}
    id = Column(Integer, primary_key=True, autoincrement=True)
    comic_last_ran = Column(DateTime)
    comic_last_id = Column(Integer)
    bit = Column(Integer, unique=True)


engine = create_engine(raw_config.get('database', 'uri'))

if raw_config.get('database', 'uri').startswith('postgres'):
    try:
        engine.execute(CreateSchema(SCHEMA))
    except ProgrammingError:
        # Schema already exists
        pass

Base.metadata.create_all(engine)

Base.metadata.bind = engine

DBSession = scoped_session(sessionmaker(bind=engine))

db_session = DBSession()

try:
    new_setting = Setting()
    new_setting.bit = 0
    db_session.add(new_setting)
    db_session.commit()
except IntegrityError:
    # Settings row has already been created
    db_session.rollback()
