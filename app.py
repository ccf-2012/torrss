from flask import Flask, render_template, jsonify, redirect, request, abort
from flask_sqlalchemy import SQLAlchemy
from flask_httpauth import HTTPBasicAuth
from http.cookies import SimpleCookie


from wtforms import Form, StringField, RadioField, SubmitField, DecimalField, IntegerField, SelectField, BooleanField
from wtforms.validators import DataRequired, NumberRange
from wtforms.widgets import PasswordInput
from apscheduler.schedulers.background import BackgroundScheduler

import os
import re
import sys
import math
import json
import shutil
import argparse
import requests as pyrequests
import feedparser
from urllib.parse import urlparse
from datetime import datetime, timedelta
from loguru import logger

import qbfunc
import myconfig


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# app.config['SECRET_KEY'] = 'mykey'
db = SQLAlchemy(app)

auth = HTTPBasicAuth()


@auth.verify_password
def verify_password(username, password):
    if username == myconfig.CONFIG.basicAuthUser and password == myconfig.CONFIG.basicAuthPass:
        return username


scheduler = BackgroundScheduler(job_defaults={'max_instances': 3})


LOG_FILE_NAME = "torrss.log"


class RSSTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    site = db.Column(db.String(64))
    rsslink = db.Column(db.String(256))
    cookie = db.Column(db.String(1024))
    title_regex = db.Column(db.String(120))
    info_regex = db.Column(db.String(120))
    title_not_regex = db.Column(db.String(120))
    info_not_regex = db.Column(db.String(120))
    min_imdb = db.Column(db.Float, default=0.0)
    size_min = db.Column(db.Integer, default=2)
    task_interval = db.Column(db.Integer, default=2)
    total_count = db.Column(db.Integer)
    accept_count = db.Column(db.Integer)
    qbcategory = db.Column(db.String(64))
    last_update = db.Column(
        db.DateTime, default=datetime.now, onupdate=datetime.now)
    active = db.Column(db.SmallInteger, default=0)

    def to_dict(self):
        return {
            'id': self.id,
            'last_update': self.last_update,
            'site': self.site,
            'task_interval': self.task_interval,
            'accept_count': self.accept_count,
            'title_regex': self.title_regex,
            'title_not_regex': self.title_not_regex,
            'info_regex': self.info_regex,
            'info_not_regex': self.info_not_regex,
            'min_imdb': self.min_imdb,
            'qbcategory': self.qbcategory,
            'active': self.active,
        }


class RSSHistory(db.Model):
    __tablename__ = 'rss_history'
    id = db.Column(db.Integer, primary_key=True)
    tid = db.Column(db.Integer)
    site = db.Column(db.String(64))
    title = db.Column(db.String(255))
    accept = db.Column(db.Integer, default=0)
    imdbstr = db.Column(db.String(32))
    addedon = db.Column(db.DateTime, default=datetime.now)
    reason = db.Column(db.String(64))
    size = db.Column(db.BigInteger)
    infoLink = db.Column(db.String(255))
    downloadLink = db.Column(db.String(255))

    def to_dict(self):
        return {
            'id': self.id,
            'addedon': self.addedon,
            'site': self.site,
            'title': self.title,
            'imdbstr': self.imdbstr,
            'reason': self.reason,
            'size': humanSize(int(self.size)),
            'accept': self.accept,
            'infoLink': self.infoLink,
        }


class RSSTaskForm(Form):
    rsslink = StringField('RSS 链接', validators=[DataRequired()])
    cookie = StringField('Cookie')
    title_regex = StringField('标题包含')
    title_not_regex = StringField('标题不含')
    info_regex = StringField('描述包含')
    info_not_regex = StringField('描述不含')
    size_min = IntegerField('大小 (GB)', default=2)
    min_imdb = DecimalField('IMDb 大于', validators=[NumberRange(min=0, max=10)])
    task_interval = IntegerField('执行间隔 (分钟)', default=2)
    qbcategory = StringField('加入qBit时带Category')
    submit = SubmitField("保存设置")


def initDatabase():
    with app.app_context():
        db.create_all()


@app.route('/')
@auth.login_required
def index():
    return render_template('rsstasks.html')


@app.route('/api/rsslogdata')
@auth.login_required
def rssHistoryData():
    query = RSSHistory.query

    # search filter
    search = request.args.get('search[value]')
    if search:
        query = query.filter(db.or_(
            RSSHistory.title.like(f'%{search}%'),
        ))
    total_filtered = query.count()

    # sorting
    order = []
    i = 0
    while True:
        col_index = request.args.get(f'order[{i}][column]')
        if col_index is None:
            break
        col_name = request.args.get(f'columns[{col_index}][data]')
        if col_name not in ['site', 'title', 'addedon', 'accept']:
            col_name = 'title'
        descending = request.args.get(f'order[{i}][dir]') == 'desc'
        col = getattr(RSSHistory, col_name)
        if descending:
            col = col.desc()
        order.append(col)
        i += 1
    if order:
        query = query.order_by(*order)

    # pagination
    start = request.args.get('start', type=int)
    length = request.args.get('length', type=int)
    query = query.offset(start).limit(length)

    # response
    return {
        'data': [user.to_dict() for user in query],
        'recordsFiltered': total_filtered,
        'recordsTotal': RSSHistory.query.count(),
        'draw': request.args.get('draw', type=int),
    }


@app.route('/rsslog')
@auth.login_required
def rssLog():
    return render_template('rsslog.html')


@app.route('/rsstasks')
@auth.login_required
def rssTaskList():
    return render_template('rsstasks.html')


@app.route('/api/rsstasksdata')
@auth.login_required
def rssTaskData():
    query = RSSTask.query

    # search filter
    search = request.args.get('search[value]')
    if search:
        query = query.filter(db.or_(
            RSSTask.site.like(f'%{search}%'),
        ))
    total_filtered = query.count()

    # sorting
    order = []
    i = 0
    while True:
        col_index = request.args.get(f'order[{i}][column]')
        if col_index is None:
            break
        col_name = request.args.get(f'columns[{col_index}][data]')
        if col_name not in ['site', 'min_imdb', 'last_update', 'accept_count']:
            col_name = 'site'
        descending = request.args.get(f'order[{i}][dir]') == 'desc'
        col = getattr(RSSTask, col_name)
        if descending:
            col = col.desc()
        order.append(col)
        i += 1
    if order:
        query = query.order_by(*order)

    # pagination
    start = request.args.get('start', type=int)
    length = request.args.get('length', type=int)
    query = query.offset(start).limit(length)

    # response
    return {
        'data': [user.to_dict() for user in query],
        'recordsFiltered': total_filtered,
        'recordsTotal': RSSTask.query.count(),
        'draw': request.args.get('draw', type=int),
    }


@app.route('/rssnew', methods=['POST', 'GET'])
@auth.login_required
def rssNew():
    form = RSSTaskForm(request.form)
    if request.method == 'POST':
        form = RSSTaskForm(request.form)
        task = RSSTask()
        task.rsslink = form.rsslink.data
        task.site = getSiteName(task.rsslink)
        task.cookie = form.cookie.data
        task.title_regex = form.title_regex.data
        task.info_regex = form.info_regex.data
        task.title_not_regex = form.title_not_regex.data
        task.info_not_regex = form.info_not_regex.data
        task.min_imdb = form.min_imdb.data
        task.size_min = form.size_min.data
        task.task_interval = form.task_interval.data
        task.qbcategory = form.qbcategory.data
        task.total_count = 0
        task.accept_count = 0
        db.session.add(task)
        db.session.commit()

        job = scheduler.add_job(rssJob, 'interval', args=[
                                task.id], minutes=task.task_interval, id=str(task.id))
        return redirect("/rsstasks")

    return render_template('rssnew.html', form=form)


@app.route('/rssedit/<id>', methods=['POST', 'GET'])
@auth.login_required
def rssEdit(id):
    # task = RSSTask.query.get(id)
    task = db.session.get(RSSTask, id)
    try:
        scheduler.remove_job(str(task.id))
    except:
        pass

    form = RSSTaskForm(request.form)
    form.rsslink.data = task.rsslink
    form.cookie.data = task.cookie
    form.title_regex.data = task.title_regex
    form.info_regex.data = task.info_regex
    form.title_not_regex.data = task.title_not_regex
    form.info_not_regex.data = task.info_not_regex
    form.min_imdb.data = task.min_imdb
    form.size_min.data = task.size_min
    form.task_interval.data = task.task_interval

    if request.method == 'POST':
        form = RSSTaskForm(request.form)
        task.rsslink = form.rsslink.data
        task.site = getSiteName(task.rsslink)
        task.cookie = form.cookie.data
        task.title_regex = form.title_regex.data
        task.info_regex = form.info_regex.data
        task.title_not_regex = form.title_not_regex.data
        task.info_not_regex = form.info_not_regex.data
        task.min_imdb = form.min_imdb.data
        task.size_min = form.size_min.data
        task.task_interval = form.task_interval.data
        # task.total_count = 0
        # task.accept_count = 0

        db.session.commit()

        job = scheduler.add_job(rssJob, 'interval', args=[
                                task.id], minutes=task.task_interval, id=str(task.id))
        return redirect("/rsstasks")

    return render_template('rssnew.html', form=form)


@app.route('/api/rssdel')
@auth.login_required
def apiRssDel():
    tid = request.args.get('taskid')
    deleted = True
    task = RSSTask.query.filter(RSSTask.id == tid).first()
    try:
        scheduler.remove_job(str(task.id))
    except:
        deleted = False
        pass

    db.session.delete(task)
    db.session.commit()
    # return redirect("/rsstasks")
    return json.dumps({'deleted': deleted}), 200, {'ContentType': 'application/json'}


# @app.route('/rsspause/<id>')
# @auth.login_required
# def rssPause(id):
#     task = RSSTask.query.filter(RSSTask.id == id).first()
#     task.active = 2
#     db.session.commit()
#     return redirect("/rsstasks")


@app.route('/api/rssactivate')
@auth.login_required
def apiRssToggleActive():
    tid = request.args.get('taskid')
    # task = RSSTask.query.get(id)
    task = db.session.get(RSSTask, tid)
    if task:
        if task.active == 0:
            task.active = 2
            try:
                scheduler.pause_job(str(task.id))
            except:
                pass
        else:
            task.active = 0
            try:
                scheduler.resume_job(str(task.id))
            except:
                pass

        # scheduler.print_jobs()
        db.session.commit()

    return json.dumps({'active': task.active}), 200, {'ContentType': 'application/json'}


@app.route('/api/rssrunonce')
@auth.login_required
def apiRunRssNow():
    tid = request.args.get('taskid')
    try:
        job = scheduler.get_job(str(tid))
        if job:
            job.modify(next_run_time=datetime.now())
    except:
        pass
    return json.dumps({'success': True}), 200, {'ContentType': 'application/json'}


class QBSettingForm(Form):
    qbhost = StringField('qBit 主机IP', validators=[DataRequired()])
    qbport = StringField('qBit 端口')
    qbuser = StringField('qBit 用户名', validators=[DataRequired()])
    qbpass = StringField('qBit 密码', widget=PasswordInput(
        hide_value=False), validators=[DataRequired()])
    submit = SubmitField("保存设置")
    # qbapirun = RadioField('qBit 种子完成后调 API, 还是执行本地 rcp.sh 脚本？', choices=[
    #     ('True', '调用 API, 适用于 qBit 跑在docker里面的情况'),
    #     ('False', '直接执行本地 rcp.sh 脚本')])
    # dockerFrom = StringField('若 qBit 在docker中，则须设置映射将docker中的路径：')
    # dockerTo = StringField('转换为以下路径：')


@app.route('/qbsetting', methods=['POST', 'GET'])
@auth.login_required
def qbitSetting():
    form = QBSettingForm()
    form.qbhost.data = myconfig.CONFIG.qbServer
    form.qbport.data = myconfig.CONFIG.qbPort
    form.qbuser.data = myconfig.CONFIG.qbUser
    form.qbpass.data = myconfig.CONFIG.qbPass
    # form.qbapirun.data = myconfig.CONFIG.apiRunProgram
    # form.dockerFrom.data = myconfig.CONFIG.dockerFrom
    # form.dockerTo.data = myconfig.CONFIG.dockerTo
    msg = ''
    if request.method == 'POST':
        form = QBSettingForm(request.form)
        myconfig.updateQBSettings(ARGS.config,
                                  form.qbhost.data,
                                  form.qbport.data,
                                  form.qbuser.data,
                                  form.qbpass.data,
                                #   form.qbapirun.data,
                                #   form.dockerFrom.data,
                                #   form.dockerTo.data,
                                  )
        # if form.qbapirun.data == 'True':
        #     authstr = '-u %s:%s ' % (myconfig.CONFIG.basicAuthUser,
        #                              myconfig.CONFIG.basicAuthPass)
        #     apiurl = 'http://%s:5006/api/torcp2' % (form.qbhost.data)
        #     postargs = '-d torhash=%I '
        #     progstr = 'curl ' + authstr + postargs + apiurl
        # else:
        #     fn = os.path.join(os.path.dirname(__file__), "rcp.sh")
        #     progstr = 'sh ' + fn + ' "%I" '
        #     scriptpath = os.path.dirname(__file__)
        #     with open(fn, 'w') as f:
        #         f.write(
        #             f"#!/bin/sh\npython3 {os.path.join(scriptpath, 'rcp.py')}  -I $1 >>{os.path.join(scriptpath, 'rcp2.log')} 2>>{os.path.join(scriptpath, 'rcp2e.log')}\n")
        #         f.close()
        #     # import stat
        #     # os.chmod(fn, stat.S_IXUSR|stat.S_IXGRP|stat.S_IXOTH)

        # r = qbfunc.setAutoRunProgram(progstr)
        # if r:
        #     msg = 'success'
        # else:
        #     msg = 'failed'
    return render_template('qbsetting.html', form=form, msg=msg)


# --------------------------------------


def tryFloat(fstr):
    try:
        f = float(fstr)
    except:
        f = 0.0
    return f


def tryint(instr):
    try:
        string_int = int(instr)
    except ValueError:
        string_int = 0
    return string_int


def humanSize(size_bytes):
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

# --------------------------------------


def validDownloadlink(downlink):
    keystr = ['passkey', 'downhash', 'totheglory.im/dl/',
              'totheglory.im/rssdd.php', 'download.php?hash=']
    return any(x in downlink for x in keystr)


def getSiteName(url):
    hostnameList = urlparse(url).netloc.split('.')
    if len(hostnameList) == 2:
        sitename = hostnameList[0]
    elif len(hostnameList) == 3:
        sitename = hostnameList[1]
    else:
        sitename = ''
    return sitename


def getAbbrevSiteName(url):
    sitename = getSiteName(url)
    SITE_ABBRES = [('chdbits', 'chd'), ('pterclub', 'pter'), ('audiences', 'aud'),
                   ('lemonhd', 'lhd'), ('keepfrds', 'frds'), ('ourbits', 'ob'),
                   ('springsunday', 'ssd'), ('totheglory', 'ttg'), ('m-team', 'mt')]
    # result = next((i for i, v in enumerate(SITE_ABBRES) if v[0] == sitename), "")
    abbrev = [x for x in SITE_ABBRES if x[0] == sitename]
    return abbrev[0][1] if abbrev else sitename


def genrSiteId(detailLink, imdbstr):
    siteAbbrev = getAbbrevSiteName(detailLink)
    if (siteAbbrev == "ttg" or siteAbbrev == "totheglory"):
        m = re.search(r"t\/(\d+)", detailLink, flags=re.A)
    else:
        m = re.search(r"id=(\d+)", detailLink, flags=re.A)
    sid = m[1] if m else ""
    if imdbstr:
        sid = sid + "_" + imdbstr
    return siteAbbrev + "_" + sid


def addTorrent(dl_entry,  size_storage_space):
    if (not myconfig.CONFIG.qbServer):
        return 400

    if not validDownloadlink(dl_entry.downlink):
        return 402

    if not myconfig.CONFIG.dryrun:
        logger.info("   >> Entry: " + dl_entry.siteid_str)

        if not qbfunc.addQbitWithTag(dl_entry, size_storage_space):
            return 400
    else:
        logger.info("   >> DRYRUN: " + dl_entry.siteid_str +
                    "\n   >> " + dl_entry.downlink)

    return 201


def existsInRssHistory(torname):
    with app.app_context():
        # exists = db.session.query(RSSHistory.id).filter_by(title=torname).first() is not None
        exists = db.session.query(db.exists().where(
            RSSHistory.title == torname)).scalar()
    return exists


def fetchInfoPage(pageUrl, pageCookie):
    cookie = SimpleCookie()
    cookie.load(pageCookie)
    cookies = {k: v.value for k, v in cookie.items()}
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        'User-Agent':
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36 Edg/109.0.1518.78",
        'Content-Type': 'text/html; charset=UTF-8'
    }

    try:
        r = pyrequests.get(pageUrl, headers=headers,
                           cookies=cookies, timeout=15)
        # r.encoding = r.apparent_encoding
        r.encoding = 'utf-8'
    except:
        return ''

    return r.text


def parseInfoPageIMDbval(doc):
    imdbval = 0
    m1 = re.search(r'IMDb.*?([0-9.]+)\s*/\s*10', doc, flags=re.I)
    if m1:
        imdbval = tryFloat(m1[1])
    doubanval = 0
    m2 = re.search(r'豆瓣评分.*?([0-9.]+)/10', doc, flags=re.I)
    if m2:
        doubanval = tryFloat(m2[1])
    if imdbval < 1 and doubanval < 1:
        ratelist = [x[1] for x in re.finditer(
            r'Rating:.*?([0-9.]+)\s*/\s*10\s*from', doc, flags=re.I)]
        if len(ratelist) >= 2:
            doubanval = tryFloat(ratelist[0])
            imdbval = tryFloat(ratelist[1])
        elif len(ratelist) == 1:
            # TODO: 不分辨douban/imdb了
            doubanval = tryFloat(ratelist[0])
            imdbval = doubanval
            # rate1 = re.search(r'Rating:.*?([0-9.]+)\s*/\s*10\s*from', doc, flags=re.A)
            # if rate1:
            #     imdbval = tryFloat(rate1[1])
        # print("   >> IMDb: %s, douban: %s" % (imdbval, doubanval))
    return imdbval, doubanval


def parseInfoPageIMDbId(doc):
    imdbstr = ''
    m1 = re.search(r'www\.imdb\.com\/title\/(tt\d+)', doc, flags=re.A)
    if m1:
        imdbstr = m1[1]
    return imdbstr


def processRssFeeds(rsstask):
    feed = feedparser.parse(rsstask.rsslink)
    rssFeedSum = 0
    rssAccept = 0

    size_storage_space = qbfunc.get_free_space()
    for item in feed.entries:
        rssFeedSum += 1
        if not hasattr(item, 'id'):
            logger.info('RSS item: No id')
            continue
        if not hasattr(item, 'title'):
            logger.info('RSS item:  No title')
            continue
        if not hasattr(item, 'link'):
            logger.info('RSS item:  No info link')
            continue
        if not hasattr(item, 'links'):
            logger.info('RSS item:  No download link')
            continue
        if len(item.links) <= 1:
            logger.info('RSS item:  No download link')
            continue

        if existsInRssHistory(item.title):
            # print("   >> exists in rss history, skip")
            continue

        logger.info("%d: %s (%s)" % (rssFeedSum, item.title,
                                     datetime.now().strftime("%H:%M:%S")))

        size_item = tryint(item.links[1]['length'])
        dbrssitem = RSSHistory(site=rsstask.site,
                               tid=rsstask.id,
                               title=item.title,
                               infoLink=item.link,
                               downloadLink=item.links[1]['href'],
                               size=size_item)

        db.session.add(dbrssitem)
        db.session.commit()

        if size_item / 1024 / 1024 < rsstask.size_min:
            dbrssitem.reason = 'SIZE_MIN'
            db.session.commit()
            continue

        if rsstask.title_regex:
            if not re.search(rsstask.title_regex, item.title, re.I):
                dbrssitem.reason = 'TITLE_REGEX'
                db.session.commit()
                continue

        if rsstask.title_not_regex:
            if re.search(rsstask.title_not_regex, item.title, re.I):
                dbrssitem.reason = 'TITLE_NOT_REGEX'
                db.session.commit()
                continue

        imdbstr = ''
        if rsstask.cookie:
            # Means: will dl wihout cookie, but no dl if cookie is wrong
            doc = fetchInfoPage(item.link, rsstask.cookie)
            if not doc:
                dbrssitem.reason = 'Fetch info page failed'
                db.session.commit()
                continue
            imdbstr = parseInfoPageIMDbId(doc)
            dbrssitem.imdbstr = imdbstr
            db.session.commit()

            if rsstask.info_regex:
                if not re.search(rsstask.info_regex, doc, flags=re.A):
                    dbrssitem.reason = 'INFO_REGEX'
                    db.session.commit()
                    continue
            if rsstask.info_not_regex:
                if re.search(rsstask.info_not_regex, doc, flags=re.A):
                    dbrssitem.reason = 'INFO_NOT_REGEX'
                    db.session.commit()
                    continue
            if rsstask.min_imdb:
                imdbval, doubanval = parseInfoPageIMDbval(doc)
                if (imdbval < rsstask.min_imdb) and (doubanval < rsstask.min_imdb):
                    # print("   >> MIN_IMDb not match")
                    dbrssitem.reason = "IMDb: %s, douban: %s" % (
                        imdbval, doubanval)
                    db.session.commit()
                    continue

        siteIdStr = genrSiteId(item.link, imdbstr)

        rssDownloadLink = item.links[1]['href']
        dbrssitem.accept = 2
        logger.info('   %s (%s), %s' %
                    (imdbstr, humanSize(int(dbrssitem.size)), rssDownloadLink))

        # if checkMediaDbNameDupe(item.title):
        #     dbrssitem.reason = "Name dupe"
        #     db.session.commit()
        #     continue

        # r = checkMediaDbTMDbDupe(item.title, imdbstr)
        # if r != 201:
        #     dbrssitem.reason = 'TMDb dupe'
        #     db.session.commit()
        #     continue

        qbcat = rsstask.qbcategory if rsstask.qbcategory else ''
        dl_entry = qbfunc.DownloadEntry()
        dl_entry.title = item.title
        dl_entry.size = tryint(item.links[1]['length'])
        dl_entry.downlink = rssDownloadLink.strip()
        dl_entry.imdb = imdbstr
        dl_entry.siteid_str = siteIdStr
        dl_entry.label = qbcat

        r = addTorrent(dl_entry, size_storage_space)
        if r == 201:
            # Downloaded
            size_storage_space -=  dl_entry.size
            dbrssitem.accept = 3
            rssAccept += 1
        else:
            dbrssitem.reason = 'qBit Error'

        db.session.commit()

    rsstask.accept_count += rssAccept
    db.session.commit()

    logger.info('RSS %s - Total: %d, Accepted: %d (%s)' %
                (rsstask.site, rssFeedSum, rssAccept, datetime.now().strftime("%H:%M:%S")))


def rssJob(id):
    with app.app_context():
        task = RSSTask.query.filter(RSSTask.id == id).first()
        if task:
            # print('Runing task: ' + task.rsslink)
            processRssFeeds(task)


def startApsScheduler():
    with app.app_context():
        tasks = RSSTask.query
        for t in tasks:
            if not scheduler.get_job(str(t.id)):
                logger.info(f"Start rss task: {t.rsslink}")
                job = scheduler.add_job(rssJob, 'interval',
                                        args=[t.id],
                                        minutes=t.task_interval,
                                        next_run_time=datetime.now()+timedelta(minutes=15),
                                        id=str(t.id))
                if ARGS.no_rss or t.active == 2:
                    job.pause()

    scheduler.start()
    scheduler.print_jobs()


def loadArgs():
    parser = argparse.ArgumentParser(
        description='Tor Rss.')
    parser.add_argument('-C', '--config', help='config file.')
    parser.add_argument('-G', '--init-password',
                        action='store_true', help='init pasword.')
    parser.add_argument('--no-rss',
                        action='store_true', help='do not start rss tasks')

    global ARGS
    ARGS = parser.parse_args()
    if not ARGS.config:
        ARGS.config = os.path.join(os.path.dirname(__file__), 'config.ini')


def main():
    loadArgs()
    initDatabase()
    myconfig.readConfig(ARGS.config)
    if ARGS.init_password:
        myconfig.generatePassword(ARGS.config)
        return
    if not myconfig.CONFIG.basicAuthUser or not myconfig.CONFIG.basicAuthPass:
        print('set user/pasword in config.ini or use "-G" argument')
        return
    startApsScheduler()
# https://stackoverflow.com/questions/14874782/apscheduler-in-flask-executes-twice
    app.run(host='0.0.0.0', port=5009, debug=True, use_reloader=False)


if __name__ == '__main__':
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    log.disabled = True

    logger.remove()
    formatstr = "{time:YYYY-MM-DD HH:mm:ss} | <level>{level: <8}</level> | - <level>{message}</level>"
    logger.add(sys.stdout, format=formatstr)
    logger.add(LOG_FILE_NAME, format=formatstr, rotation="500 MB")
    # logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD at HH:mm:ss}</green> | <level>{message}</level>")
    main()
