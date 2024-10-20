
import qbittorrentapi
import myconfig
import urllib.parse
import shutil
import math
import time
from loguru import logger
logger = logger.bind(name='qbittorrent_mod')
DISK_SPACE_MARGIN = 2004800000  # 2G before disk full


def getTorrentFirstTracker(torrent):
    noneTracker = {"url": "", "msg": ""}
    firstTracker = next(
        (tracker for tracker in torrent.trackers if tracker['status'] > 0), noneTracker)
    return firstTracker


def abbrevTracker(trackerstr):
    hostnameList = urllib.parse.urlparse(trackerstr).netloc.split('.')
    if len(hostnameList) == 2:
        abbrev = hostnameList[0]
    elif len(hostnameList) == 3:
        abbrev = hostnameList[1]
    else:
        abbrev = ''
    return abbrev


def getTorrentByHash(torhash):
    qbClient = qbittorrentapi.Client(
        host=myconfig.CONFIG.qbServer, port=myconfig.CONFIG.qbPort, username=myconfig.CONFIG.qbUser, password=myconfig.CONFIG.qbPass)

    try:
        qbClient.auth_log_in()
    except:
        return '', '', '', '', '', ''

    # if not qbClient:
    #     return '', '', '', '', ''

    # try:
    #     # torrent = qbClient.torrents_properties(torrent_hash=torhash)
    #     torrent = qbClient.torrents_trackers(torrent_hash=torhash)
    # except:
    #     print('Torrent hash NOT found.')
    #     return '', '', '', '', ''

    torlist = qbClient.torrents_info(torrent_hashes=torhash, limit=3)
    if len(torlist) <= 0:
        print('Torrent hash NOT found.')
        return '', '', '', '', '', ''
    torrent = torlist[0]
    tracker = getTorrentFirstTracker(torrent)

    return torrent.content_path, torrent.hash, str(torrent.size), torrent.tags, torrent.save_path, abbrevTracker(tracker["url"])


def getAutoRunProgram():
    qbClient = qbittorrentapi.Client(
        host=myconfig.CONFIG.qbServer, port=myconfig.CONFIG.qbPort, username=myconfig.CONFIG.qbUser, password=myconfig.CONFIG.qbPass)

    try:
        qbClient.auth_log_in()
    except qbittorrentapi.LoginFailed as e:
        print(e)
        return False
    except:
        return False

    if not qbClient:
        return False

    prefs = qbClient.app_preferences()
    autoprog = prefs["autorun_program"]
    return autoprog


def setAutoRunProgram(prog):
    qbClient = qbittorrentapi.Client(
        host=myconfig.CONFIG.qbServer, port=myconfig.CONFIG.qbPort, username=myconfig.CONFIG.qbUser, password=myconfig.CONFIG.qbPass)

    try:
        qbClient.auth_log_in()
    except qbittorrentapi.LoginFailed as e:
        print(e)
        return False
    except:
        return False

    if not qbClient:
        return False

    qbClient.app_set_preferences(
        prefs={"autorun_enabled": True, "autorun_program": prog})
    return True


def qbDeleteTorrent(qbClient, tor_hash):
    try:
        qbClient.torrents_delete(True, torrent_hashes=tor_hash)
    except Exception as ex:
        print('There was an error during client.torrents_delete: %s', ex)


def human_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    sign = ''
    if size_bytes < 0:
        sign = '-'
        size_bytes = -size_bytes

    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return sign+"%s %s" % (s, size_name[i])


def get_free_space():
    # _, _, free = psutil.disk_usage('/')
    # return free
    # TODO: api/psutil, which one?
    qbClient = qbittorrentapi.Client(
        host=myconfig.CONFIG.qbServer, port=myconfig.CONFIG.qbPort, username=myconfig.CONFIG.qbUser, password=myconfig.CONFIG.qbPass)

    try:
        qbClient.auth_log_in()
    except qbittorrentapi.LoginFailed as e:
        print(e)
        return -1

    if not qbClient:
        return -1

    try:
        r = qbClient.sync_maindata(rid=0)
        return r['server_state']['free_space_on_disk']
    except Exception:
        logger.error('Error getting qBittorrent main data.')
        return -1


def space_for_torrent(client, torrents, entry, size_storage_space):
    size_new_torrent = entry.size
    # logger.info('New torrent: %s, need %s.' %
    #             (entry.title, convert_size(size_new_torrent)))

    # for all Downloading torrents in qbit, calculate bytes left to download
    size_left_to_complete = 0
    # uncompleted_torrents = [x for x in torrents if (x['state'] == 'downloading'] or x['state'] == 'stalledDL']) ]
    uncompleted_torrents = [x for x in torrents if x['progress'] < 1]
    for torrent in uncompleted_torrents:
        size_left_to_complete += torrent['amount_left']
        # size_left_to_complete += (torrent['total_size'] - torrent['downloaded'])
    # logger.info('Uncomplete download: %s.' %
    #             convert_size(size_left_to_complete))

    remain_space = size_storage_space - size_left_to_complete
    logger.info(f'   >> (hdd_free) {human_size(size_storage_space)} - (uncomplete) {human_size(size_left_to_complete)} - '
                f'(new_tor) {human_size(size_new_torrent)} = {human_size(remain_space - size_new_torrent)}.')
    # logger.info(f'  (remain_space - size_new_torrent) = {remain_space - size_new_torrent}.')
    if (remain_space - size_new_torrent) > DISK_SPACE_MARGIN:
        # if size_storage_space - size_left_to_complete - size_new_torrent > DISK_SPACE_MARGIN:
        # enough space to add the new torrent
        logger.info(
            f'   => Add : ({human_size(size_new_torrent)}) {entry.title}.')
        return True

    # Sort completed torrents by seeding time
    completed_torrents = sorted(
        [x for x in torrents if x['progress'] == 1],
        key=lambda t: t['seeding_time'],
        reverse=True
    )
    logger.info(
        f'   -- {len(completed_torrents)}/{len(torrents)} finished/total torrents.')

    # Loop through completed torrents and delete until there is enough space
    torrents_to_del = []
    space_to_del = 0
    for tor_complete in completed_torrents:
        torrents_to_del.append(tor_complete)
        space_to_del += tor_complete['downloaded']
        logger.info(
            f'   >> {tor_complete["name"]} : {human_size(tor_complete["downloaded"])} ')
        logger.info(f'   :: size_storage_space({size_storage_space}) + space_to_del({space_to_del}) '+
                    f'- size_left_to_complete ({size_left_to_complete}) ' +
                    f'- size_new_torrent ({size_new_torrent}) '+
                    f'= {human_size(size_storage_space + space_to_del - size_left_to_complete - size_new_torrent)}')
        if (size_storage_space + space_to_del - size_left_to_complete - size_new_torrent) > DISK_SPACE_MARGIN:
            for tor_to_del in torrents_to_del:
                logger.info(
                    f'Deleting: {tor_to_del["name"]} to free {human_size(tor_to_del["downloaded"])}.')
                qbDeleteTorrent(client, tor_to_del['hash'])
                time.sleep(3)
            # Enough space now available, add the new torrent
            # time.sleep(5)
            # size_storage_space = get_free_space(client)
            # logger.info('Free space: %s.' % convert_size(size_storage_space))
            return True
    remain_space = size_storage_space + space_to_del - size_left_to_complete
    # logger.info('   !!! not enough: %s + %s - %s = %s.' % (convert_size(size_storage_space), convert_size(space_to_del), convert_size(
    #     size_left_to_complete), convert_size(remain_space)))

    return False


def addQbitWithTag(entry, size_storage_space):
    qbClient = qbittorrentapi.Client(
        host=myconfig.CONFIG.qbServer, port=myconfig.CONFIG.qbPort, username=myconfig.CONFIG.qbUser, password=myconfig.CONFIG.qbPass)

    try:
        qbClient.auth_log_in()
    except qbittorrentapi.LoginFailed as e:
        print(e)
        return False

    if not qbClient:
        return False

    try:
        torrents = qbClient.torrents_info()
        # logger.info(f'   >>  {len(torrents)} torrents in client.')
    except:
        logger.debug('  !! Fail to load torrent list.')
        # client.disconnect()
        return False

    # logger.info(f'   >> Free space: {convert_size(size_storage_space)}.')
    enough_space = space_for_torrent(
        qbClient, torrents, entry, size_storage_space)
    if not enough_space:
        logger.info(f'   !! No enough space. Skip: {entry.title}')
        return False

    try:
        if entry.siteid_str:
            result = qbClient.torrents_add(
                urls=entry.downlink,
                save_path=entry.siteid_str,
                category=entry.label,
                tags=[entry.imdb],
                use_auto_torrent_management=False)
        else:
            result = qbClient.torrents_add(
                urls=entry.downlink,
                category=entry.label,
                tags=[entry.imdb],
                use_auto_torrent_management=False)
        if 'OK' in result.upper():
            pass
            logger.success(
                f'   >> Torrent added: {entry.title} ({human_size(entry.size)})')
        else:
            logger.warning(
                '   >> Torrent not added! something wrong with qb api ...')
    except Exception as e:
        logger.error('   >> Torrent not added! Exception: '+str(e))
        return False
    return True


def addQbitFileWithTag(filecontent, imdbtag, siteIdStr=None):
    qbClient = qbittorrentapi.Client(
        host=myconfig.CONFIG.qbServer, port=myconfig.CONFIG.qbPort, username=myconfig.CONFIG.qbUser, password=myconfig.CONFIG.qbPass)

    try:
        qbClient.auth_log_in()
    except qbittorrentapi.LoginFailed as e:
        print(e)
        return False

    if not qbClient:
        return False

    try:
        # curr_added_on = time.time()
        if siteIdStr:
            result = qbClient.torrents_add(
                torrent_files=filecontent,
                save_path=siteIdStr,
                # download_path=download_location,
                # category=timestamp,
                tags=[imdbtag],
                use_auto_torrent_management=False)
        else:
            result = qbClient.torrents_add(
                torrent_files=filecontent,
                tags=[imdbtag],
                use_auto_torrent_management=False)
        # breakpoint()
        if 'OK' in result.upper():
            pass
            # print('   >> Torrent added.')
        else:
            print('   >> Torrent not added! something wrong with qb api ...')
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
