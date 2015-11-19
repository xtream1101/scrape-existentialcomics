import os
import sys
import yaml
import signal
import argparse
from custom_utils.custom_utils import CustomUtils
from custom_utils.exceptions import *
from custom_utils.sql import *


class ExistentialComics(CustomUtils):

    def __init__(self, base_dir, restart=False, proxies=[], url_header=None):
        super().__init__()
        # Make sure base_dir exists and is created
        self._base_dir = base_dir

        # Do we need to restart
        self._restart = restart

        # Set url_header
        self._url_header = self.set_url_header(url_header)

        # If we have proxies then add them
        if len(proxies) > 0:
            self.set_proxies(proxies)
            self.log("Using IP: " + self.get_current_proxy())

        # Setup database
        self._db_setup()

        # Start parsing the site
        self.start()

    def start(self):
        latest = self.get_latest()

        if self._restart is True:
            progress = 0
        else:
            progress = self.sql.get_progress()

        if latest == progress:
            # Nothing new to get
            self.cprint("Already have the latest")
            return

        for i in range(progress + 1, latest + 1):
            self.cprint("Getting comic: " + str(i))
            if self._restart is True:
                check_data = self._db_session.query(Data).filter(Data.id == i).first()
                if check_data is not None:
                    continue

            if self.parse(i) is not False:
                self.sql.update_progress(i)

    def get_latest(self):
        """
        Parse a page to get the newest id posted
        :return: id of the newest item
        """
        self.cprint("##\tGetting newest upload id...\n")

        url = "http://existentialcomics.com/"
        # Get the page data
        try:
            data = self.get_site(url, self._url_header)
        except RequestsError as e:
            print("Error getting latest: " + str(e))
            sys.exit(0)

        prev = data.find('area', {'alt': 'previous'})

        max_id = int(prev['href'].split('/')[-1]) + 1
        self.cprint("##\tNewest upload: " + str(max_id) + "\n")

        return int(max_id)

    def parse(self, id_):
        """
        Using the items id, get it
        :param id_: id of the item
        :return:
        """
        # There is no 0 item
        if id_ == 0:
            return False

        url = "http://existentialcomics.com/comic/" + str(id_)
        try:
            data = self.get_site(url, self._url_header)
        except RequestsError as e:
            err = str(e)
            print("Error getting (" + url + "): " + err)

            return False

        prop = {}

        # Every prop needs an id
        prop['id'] = str(id_)

        prop['title'] = data.find('h3').text

        # Some comics consist of a few images
        comic_image = data.find_all('img', {'class': 'comicImg'})
        prop['img_list'] = []
        for img in comic_image:
            prop['img_list'].append(img['src'])

        prop['img_count'] = len(prop['img_list'])

        alt_text = data.find('div', {'class': 'altText'})
        if alt_text:
            prop['alt'] = alt_text.text.strip()
        else:
            prop['alt'] = ""

        explanation = data.find('div', {'id': 'explainHidden'})
        if explanation:
            prop['explanation'] = explanation.text.strip()
        else:
            prop['explanation'] = ""

        philosophers = data.find('div', {'id': 'philosophers-comic'})
        prop['philosopher_list'] = []
        if philosophers:
            for philosopher in philosophers.find_all('a'):
                philosopher_id = philosopher['href'].split('/')[-1]
                philosopher_name = philosopher.text.strip()
                prop['philosopher_list'].append({'safe_name': philosopher_id,
                                                 'name': philosopher_name
                                                 })

        #####
        # Download items if needed
        #####
        for index, img in enumerate(prop['img_list']):
            file_ext = self.get_file_ext(img)
            file_name = self.sanitize(str(prop['id'])) + '-' + str(index)

            prop['save_path'] = os.path.join(self._base_dir,
                                             prop['id'][-1],
                                             file_name + file_ext
                                             )

            self.download(img, prop['save_path'], self._url_header)

        self._save_meta_data(prop)

        # Everything was successful
        return True

    def _save_meta_data(self, data):
        check_comic = self._db_session.query(Data)\
                                      .filter(Data.id == data['id'])\
                                      .first()

        if check_comic is None:  # If philosopher does not exist, add it
            comic_data = Data(id=data['id'],
                              added_utc=self.get_utc_epoch(),
                              title=data['title'],
                              img_count=data['img_count'],
                              alt=data['alt'],
                              explanation=data['explanation'],
                              )
            self._db_session.add(comic_data)

        try:
            self._db_session.commit()
        except sqlalchemy.exc.IntegrityError:
            # tried to add an item to the database which was already there
            pass

        # Save tags in their own table
        self._save_philosopher_data(data['philosopher_list'], data['id'])

    def _save_philosopher_data(self, philosophers, data_id):
        philosopher_id_list = []
        for philosopher in philosophers:
            comic_philosopher = self._db_session.query(Philosopher)\
                                                .filter(Philosopher.safe_name == philosopher['safe_name'])\
                                                .first()

            if comic_philosopher is None:  # If philosopher does not exist, add it
                comic_philosopher = Philosopher(
                                        safe_name=philosopher['safe_name'],
                                        name=philosopher['name'],
                                        )
                self._db_session.add(comic_philosopher)
                self._db_session.flush()

            philosopher_id_list.append(comic_philosopher.id)

        try:
            self._db_session.commit()
        except sqlalchemy.exc.IntegrityError:
            # tried to add an item to the database which was already there
            pass

        # Now add philosophers to data object in DataPhilosopher
        # Needs to be done after the tags have been commited to database
        #   because of forginkey constraint
        for philosopher_id in philosopher_id_list:
            check_data_philosopher = self._db_session.query(DataPhilosopher)\
                                                     .filter(and_(DataPhilosopher.philosopher_id == philosopher_id,
                                                                  DataPhilosopher.data_id == data_id
                                                                  )
                                                             )\
                                                     .first()
            if check_data_philosopher is None:  # If philosopher does not exist, add it
                comic_data_philosopher = DataPhilosopher(philosopher_id=philosopher_id,
                                                         data_id=data_id
                                                         )
                self._db_session.add(comic_data_philosopher)
        try:
            self._db_session.commit()
        except sqlalchemy.exc.IntegrityError:
            # tried to add an item to the database which was already there
            pass

    def _db_setup(self):
        # Version of this database
        db_version = 1
        db_file = os.path.join(self._base_dir, "existentialcomics.sqlite")
        self.sql = Sql(db_file, db_version)
        is_same_version = self.sql.set_up_db()
        if not is_same_version:
            # Update database to work with current version
            pass

        # Get session
        self._db_session = self.sql.get_session()


# Custom table for the site
class Data(Base):
    __tablename__ = 'data'
    id          = Column(Integer,     primary_key=True, autoincrement=False)
    added_utc   = Column(Integer,     nullable=False)
    title       = Column(String(100), nullable=False)
    img_count   = Column(Integer,     nullable=False)
    alt         = Column(String,      nullable=False)
    explanation = Column(String,      nullable=False)


class Philosopher(Base):
    __tablename__ = 'philosophers'
    id        = Column(Integer,     primary_key=True, autoincrement=True)
    safe_name = Column(String(100), nullable=False)
    name      = Column(String(100), nullable=False)


class DataPhilosopher(Base):
    __tablename__ = 'data_philosophers'
    philosopher_id = Column(Integer, ForeignKey(Philosopher.id))
    data_id        = Column(Integer, ForeignKey(Data.id))
    __table_args__ = (
        PrimaryKeyConstraint('philosopher_id', 'data_id'),
        )


def signal_handler(signal, frame):
    print("")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)

    # Deal with args
    parser = argparse.ArgumentParser(description='Scrape site and archive data')
    parser.add_argument('-c', '--config', help='Config file')
    parser.add_argument('-d', '--dir', help='Absolute path to save directory')
    parser.add_argument('-r', '--restart', help='Set to start parsing at 0', action='store_true')
    args = parser.parse_args()

    # Set defaults
    save_dir = None
    restart = None
    proxy_list = []

    if args.config is not None:
        # Load config values
        if not os.path.isfile(args.config):
            print("No config file found")
            sys.exit(0)

        with open(args.config, 'r') as stream:
            config = yaml.load(stream)

        # Check config file first
        if 'save_dir' in config:
            save_dir = config['save_dir']
        if 'restart' in config:
            restart = config['restart']

        # Proxies can only be set via config file
        if 'proxies' in config:
            proxy_list = config['proxies']

    # Command line args will overwrite config args
    if args.dir is not None:
        save_dir = args.dir

    if restart is None or args.restart is True:
        restart = args.restart

    # Check to make sure we have our args
    if args.dir is None and save_dir is None:
        print("You must supply a config file with `save_dir` or -d")
        sys.exit(0)

    save_dir = CustomUtils().create_path(save_dir, is_dir=True)

    # Start the scraper
    scrape = ExistentialComics(save_dir, restart=restart, proxies=proxy_list)

    print("")
