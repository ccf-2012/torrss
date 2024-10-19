import os
import time
import math
from datetime import datetime

from loguru import logger
from requests import Session
from requests.exceptions import RequestException


logger = logger.bind(name='qbittorrent_mod')
DISK_SPACE_MARGIN = 20048000000 # 2G before disk full
DISK_SPACE_100G = 102400000000 # skip torrent check if disk space > 100G

def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    sign = ''
    if size_bytes < 0:
        sign = '-'
        size_bytes = -size_bytes;

    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return sign+"%s %s" % (s, size_name[i])


class OutputQBitTorrentMod:
    """
    Example:

      qbittorrent:
        username: <USERNAME> (default: (none))
        password: <PASSWORD> (default: (none))
        host: <HOSTNAME> (default: localhost)
        port: <PORT> (default: 8080)
        use_ssl: <SSL> (default: False)
        verify_cert: <VERIFY> (default: True)
        path: <OUTPUT_DIR> (default: (none))
        label: <LABEL> (default: (none))
        tags: <TAGS> (default: (none))
        maxupspeed: <torrent upload speed limit> (default: 0)
        maxdownspeed: <torrent download speed limit> (default: 0)
        add_paused: <ADD_PAUSED> (default: False)
    """

    schema = {
        'anyOf': [
            {'type': 'boolean'},
            {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string'},
                    'password': {'type': 'string'},
                    'host': {'type': 'string'},
                    'port': {'type': 'integer'},
                    'use_ssl': {'type': 'boolean'},
                    'verify_cert': {'type': 'boolean'},
                    'path': {'type': 'string'},
                    'label': {'type': 'string'},
                    'tags': {'type': 'array', 'items': {'type': 'string'}},
                    'maxupspeed': {'type': 'integer'},
                    'maxdownspeed': {'type': 'integer'},
                    'fail_html': {'type': 'boolean'},
                    'add_paused': {'type': 'boolean'},
                    'skip_check': {'type': 'boolean'},
                },
                'additionalProperties': False,
            },
        ]
    }

    def __init__(self):
        super().__init__()
        self.session = Session()
        self.api_url_login = None
        self.api_url_upload = None
        self.api_url_download = None
        self.api_url_info = None
        self.url = None
        self.connected = False
        self.api_free_space = 0

    def _request(self, method, url, msg_on_fail=None, **kwargs):
        try:
            response = self.session.request(method, url, **kwargs)
            if response.text == "Ok.":
                return True
            msg = msg_on_fail if msg_on_fail else f'Failure. URL: {url}, data: {kwargs}'
        except RequestException as e:
            msg = str(e)
        logger.error('Error when trying to send request to qBittorrent: {}', msg)
        return False

    def check_api_version(self, msg_on_fail, verify=True):
        try:
            url = self.url + "/api/v2/app/webapiVersion"
            response = self.session.request('get', url, verify=verify)
            if response.status_code != 404:
                self.api_url_login = '/api/v2/auth/login'
                self.api_url_upload = '/api/v2/torrents/add'
                self.api_url_download = '/api/v2/torrents/add'
                self.api_url_info = '/api/v2/torrents/info'
                return response

            url = self.url + "/version/api"
            response = self.session.request('get', url, verify=verify)
            if response.status_code != 404:
                self.api_url_login = '/login'
                self.api_url_upload = '/command/upload'
                self.api_url_download = '/command/download'
                self.api_url_info = '/query/torrents'
                return response

            msg = f'Failure. URL: {url}' if not msg_on_fail else msg_on_fail
        except RequestException as e:
            msg = str(e)
        raise Exception(f'Error when trying to send request to qBittorrent: {msg}')

    def connect(self, config):
        """
        Connect to qBittorrent Web UI. Username and password not necessary
        if 'Bypass authentication for localhost' is checked and host is
        'localhost'.
        """
        self.url = '{}://{}:{}'.format(
            'https' if config['use_ssl'] else 'http', config['host'], config['port']
        )
        self.check_api_version('Check API version failed.', verify=config['verify_cert'])
        if config.get('username') and config.get('password'):
            data = {'username': config['username'], 'password': config['password']}
            if not self._request(
                'post',
                self.url + self.api_url_login,
                data=data,
                msg_on_fail='Authentication failed.',
                verify=config['verify_cert'],
            ):
                raise Exception('Not connected.')
        logger.debug('Successfully connected to qBittorrent')
        self.connected = True

    def get_free_space(self, client):
        # TODO: use qbittorrentapi.Client
        try:
            r = client.sync_maindata(rid=0)
            return r['server_state']['free_space_on_disk']
        except RequestException:
            logger.error('Error getting qBittorrent main data.')
            return -1

        # if not self.connected:
        #     raise plugin.PluginError('Not connected.')

        # sync_maindata_url = '/api/v2/sync/maindata?rid=0'
        # try:
        #     response = self.session.request(
        #         'get', 
        #         self.url + sync_maindata_url)
        # except RequestException:
        #     logger.error('Error getting qBittorrent main data.')
        #     return -1
        
        # if response.status_code != 200:
        #     logger.error(
        #         'Error getting qBittorrent main data: {}', response.status_code )
        #     return -1
        # data = response.json()
        # self.api_free_space = data['server_state']['free_space_on_disk']
        # return self.api_free_space
    
    @staticmethod
    def client(host: str, port: int, username: str, password: str):
        """
        Import client or abort task
        """
        try:
            import qbittorrentapi
        except ImportError:
            raise Exception(issued_by='from_qbittorrent', missing='qbittorrent-api')

        return qbittorrentapi.Client(host=host, port=port, username=username, password=password)

    def load_torrents(self, client):
        try:
            torrents = client.torrents_info()
            logger.info('Currently %d torrents in client.' % (len(torrents)))
            return True, torrents
        except:
            return False, []
    
    def delete_torrent(self, client, tor_hash):
        try:
            client.torrents_pause(torrent_hashes=tor_hash)
            time.sleep(1)
            client.torrents_delete(True, torrent_hashes=tor_hash)
        except Exception as ex:
            logger.error(
                'There was an error during client.torrents_delete: %s', ex)
                
    def space_for_torrent(self, client, torrents, entry, size_accept):
        size_new_torrent = entry.get("size")
        logger.info('New torrent: %s, need %s.' % (entry.get("title"), convert_size(size_new_torrent)))
        size_storage_space = self.get_free_space(client)
        logger.info('Free space: %s.' % convert_size(size_storage_space))

        # for all Downloading torrents in qbit, calculate bytes left to download
        size_left_to_complete = 0
        uncompleted_torrents = [x for x in torrents if x['state']=='downloading']
        for torrent in uncompleted_torrents:
            size_left_to_complete += torrent['amount_left']
            # size_left_to_complete += (torrent['total_size'] - torrent['downloaded'])
        logger.info('uncomplete download: %s.' % convert_size(size_left_to_complete))

        remain_space = size_storage_space - size_left_to_complete - size_accept
        logger.info('remain sapce: %s - %s - %s - %s = %s.' % (convert_size(size_storage_space), convert_size(size_left_to_complete), convert_size(size_new_torrent), convert_size(size_accept), convert_size(remain_space)))
        if remain_space > size_new_torrent + DISK_SPACE_MARGIN:
        # if size_storage_space - size_left_to_complete - size_new_torrent > DISK_SPACE_MARGIN:
            # enough space to add the new torrent
            return True
        
        # Sort completed torrents by seeding time
        completed_torrents = sorted(
            [x for x in torrents if x['progress']==1],
            key=lambda t: t['seeding_time'],
            reverse=True
        )
        
        torrents_to_del = []
        # Loop through completed torrents and delete until there is enough space
        for tor_complete in completed_torrents:
            torrents_to_del.append(tor_complete)
            size_storage_space += tor_complete['downloaded']
            if size_storage_space - size_left_to_complete - size_accept > size_new_torrent + DISK_SPACE_MARGIN:
                # Enough space now available, add the new torrent
                for tor_to_del in torrents_to_del:
                    logger.info('Deleting: %s to free %s.' % (tor_to_del['name'], convert_size(tor_to_del['downloaded'])))
                    self.delete_torrent(client, tor_to_del['hash'])
                    time.sleep(3)
                time.sleep(5)
                size_storage_space = self.get_free_space(client)
                logger.info('Free space: %s.' % convert_size(size_storage_space))
                return True
        return False
                
    def check_torrent_exists(self, hash_torrent, verify_cert):
        if not self.connected:
            raise Exception('Not connected.')

        if not isinstance(hash_torrent, str):
            logger.error('Error getting torrent info, invalid hash {}', hash_torrent)
            return False

        hash_torrent = hash_torrent.lower()

        logger.debug(f'Checking if torrent with hash {hash!r} already in session.')

        url = f'{self.url}{self.api_url_info}'
        params = {'hashes': hash_torrent}

        try:
            respose = self.session.request(
                'get',
                url,
                params=params,
                verify=verify_cert,
            )
        except RequestException:
            logger.error('Error getting torrent info, request to hash {} failed', hash_torrent)
            return False

        if respose.status_code != 200:
            logger.error(
                'Error getting torrent info, hash {} search returned',
                hash_torrent,
                respose.status_code,
            )
            return False

        check_file = respose.json()

        if isinstance(check_file, list) and check_file:
            logger.warning('File with hash {} already in qbittorrent', hash_torrent)
            return True

        return False

    def add_torrent_file(self, entry, data, verify_cert):
        file_path = entry['file']
        if not self.connected:
            raise Exception('Not connected.')

        multipart_data = {k: (None, v) for k, v in data.items()}
        with open(file_path, 'rb') as f:
            multipart_data['torrents'] = f
            if not self._request(
                'post',
                self.url + self.api_url_upload,
                msg_on_fail='Failed to add file to qBittorrent',
                files=multipart_data,
                verify=verify_cert,
            ):
                entry.fail(f'Error adding file `{file_path}` to qBittorrent')
                return
        logger.debug('Added torrent file {} to qBittorrent', file_path)

    def add_torrent_url(self, entry, data, verify_cert):
        url = entry['url']
        if not self.connected:
            raise Exception('Not connected.')

        data['urls'] = url
        multipart_data = {k: (None, v) for k, v in data.items()}
        if not self._request(
            'post',
            self.url + self.api_url_download,
            msg_on_fail=f'Failed to add url to qBittorrent: {url}',
            files=multipart_data,
            verify=verify_cert,
        ):
            entry.fail(f'Error adding url `{url}` to qBittorrent')
            return
        logger.debug('Added url {} to qBittorrent', url)

    @staticmethod
    def prepare_config(config):
        if isinstance(config, bool):
            config = {'enabled': config}
        config.setdefault('enabled', True)
        config.setdefault('host', 'localhost')
        config.setdefault('port', 8080)
        config.setdefault('use_ssl', False)
        config.setdefault('verify_cert', True)
        config.setdefault('label', '')
        config.setdefault('tags', [])
        config.setdefault('maxupspeed', 0)
        config.setdefault('maxdownspeed', 0)
        config.setdefault('fail_html', True)
        return config

    def add_entries(self, task, config):
        client = self.client(
            config['host'], int(config['port']), config['username'], config['password']
        )
        # Load torrents in qBittorrent
        # size_storage_space = self.api_free_space()
        torlist_loaded, torrents = self.load_torrents(client)
        if not torlist_loaded:
            logger.debug('Fail to load torrent list.')
            # client.disconnect()
            return

        size_accept = 0
        for entry in task.accepted:
            # make space for new torrent
            enough_space = self.space_for_torrent(client, torrents, entry, size_accept)
            if not enough_space:
                logger.info('No enough disk space left, skip torrent: {}', entry['title'])
                continue
            size_accept += entry.get("size")

            form_data = {}
            try:
                save_path = entry.render(entry.get('path', config.get('path', '')))
                if save_path:
                    form_data['savepath'] = save_path
            except:
                logger.error('Error setting path for {}', entry['title'])

            label = entry.render(entry.get('label', config.get('label', '')))
            if label:
                form_data['label'] = label  # qBittorrent v3.3.3-
                form_data['category'] = label  # qBittorrent v3.3.4+

            tags = entry.get('tags', []) + config.get('tags', [])
            if tags:
                try:
                    form_data['tags'] = entry.render(",".join(tags))
                except: 
                    logger.error('Error rendering tags for {}', entry['title'])
                    form_data['tags'] = ",".join(tags)

            add_paused = entry.get('add_paused', config.get('add_paused'))
            if add_paused:
                form_data['paused'] = 'true'

            skip_check = entry.get('skip_check', config.get('skip_check'))
            if skip_check:
                form_data['skip_checking'] = 'true'

            maxupspeed = entry.get('maxupspeed', config.get('maxupspeed'))
            if maxupspeed:
                form_data['upLimit'] = maxupspeed * 1024

            maxdownspeed = entry.get('maxdownspeed', config.get('maxdownspeed'))
            if maxdownspeed:
                form_data['dlLimit'] = maxdownspeed * 1024

            is_magnet = entry['url'].startswith('magnet:')

            if task.manager.options.test:
                logger.info('Test mode.')
                logger.info('Would add torrent to qBittorrent with:')
                if not is_magnet:
                    logger.info('File: {}', entry.get('file'))
                else:
                    logger.info('Url: {}', entry.get('url'))
                logger.info('Save path: {}', form_data.get('savepath'))
                logger.info('Label: {}', form_data.get('label'))
                logger.info('Tags: {}', form_data.get('tags'))
                logger.info('Paused: {}', form_data.get('paused', 'false'))
                logger.info('Skip Hash Check: {}', form_data.get('skip_checking', 'false'))
                if maxupspeed:
                    logger.info('Upload Speed Limit: {}', form_data.get('upLimit'))
                if maxdownspeed:
                    logger.info('Download Speed Limit: {}', form_data.get('dlLimit'))
                continue

            if self.check_torrent_exists(
                entry.get('torrent_info_hash'), config.get('verify_cert')
            ):
                continue

            if not is_magnet:
                if 'file' not in entry:
                    entry.fail('File missing?')
                    continue
                if not os.path.exists(entry['file']):
                    tmp_path = os.path.join(task.manager.config_base, 'temp')
                    logger.debug('entry: {}', entry)
                    logger.debug('temp: {}', ', '.join(os.listdir(tmp_path)))
                    entry.fail("Downloaded temp file '%s' doesn't exist!?" % entry['file'])
                    continue
                self.add_torrent_file(entry, form_data, config['verify_cert'])
            else:
                self.add_torrent_url(entry, form_data, config['verify_cert'])

    def addQbitWithTag(self, config, dl_entry):
        client = self.client(
            config['host'], int(config['port']), config['username'], config['password']
        )
        # Load torrents in qBittorrent
        # size_storage_space = self.api_free_space()
        torlist_loaded, torrents = self.load_torrents(client)
        if not torlist_loaded:
            logger.debug('Fail to load torrent list.')
            # client.disconnect()
            return

        size_accept = 0

        enough_space = self.space_for_torrent(client, torrents, dl_entry, size_accept)
        if not enough_space:
            logger.info('No enough disk space left, skip torrent: {}', dl_entry.title)
            return
        size_accept += dl_entry.size

        form_data = {}
        if dl_entry.site_str:
            form_data['save_path']=dl_entry.site_str
        if dl_entry.label:
            form_data['label'] = dl_entry.label  # qBittorrent v3.3.3-
            form_data['category'] = dl_entry.label  # qBittorrent v3.3.4+
        if dl_entry.imdb_tag:
            form_data['tags'] = dl_entry.imdb_tag

        self.add_torrent_url(entry, form_data, config['verify_cert'])

        try:
            # curr_added_on = time.time()
            if download.site_str:
                result = self.add_torrent_url(
                    urls=download.down_link,
                    save_path=download.site_str,
                    # download_path=download_location,
                    category=download.qbcat,
                    tags=[download.imdb],
                    use_auto_torrent_management=False)
            else:
                result = self.add_torrent_url(
                    urls=download.down_link,
                    category=download.site_str,
                    tags=[download.imdb],
                    use_auto_torrent_management=False)
            # breakpoint()
            if 'OK' in result.upper():
                pass
                # print('   >> Torrent added.')
            else:
                logger.info('   >> Torrent not added! something wrong with qb api ...')
        except Exception as e:
            print('   >> Torrent not added! Exception: '+str(e))
            return False

        return True



class DownloadEntry:
    def __init__(self):
        super().__init__()
        self.downlink = ''
        self.title = ''
        self.siteid_str = ''
        self.imdb = ''
        self.label = ''
        self.size = 0

