#!/usr/bin/env python
# coding: utf-8
'''
author: gabriel pettier & mathieu virbel
licence lgpl

require python-irclib
'''

import sys
import hmac
import binascii
import requests
import getpass
from requests.auth import HTTPBasicAuth
from json import dumps, loads
from hashlib import sha1
from ircbot import SingleServerIRCBot
from flask import Flask, request, abort
from threading import Thread
from random import randint

SERVERS = [('irc.freenode.net', 6667)]
SECRET = 'XXX'
COLOR_REPO = 8
COLOR_BRANCH = 4
COLOR_ISSUE = 4
COLOR_USER = 9
COLOR_URL = 15

NICKNAME = 'KGB-%s' % randint(64, 128)
COMMAND_PREFIX = '-help'
EXISTING_SIGNALS = (
    'push,issue,commit_comment,pull_request,gollum,watch,'
    'download,fork,fork_apply,member,public,status').split(',')

DEFAULT_SIGNALS = (
    'push,issues,commit_comment,pull_request,fork_apply,member').split(',')

if SECRET == '':
    print 'No SECRET defined. Edit this file, and add a secret!'
    sys.exit(1)

short_url_cache = {}

def usage(command=None):
    ''' display usage to command line call
    '''
    return {
        'quit': 'quit the channel',
        'join [channel]': 'join the given channel',
        'follow [repository]': 'start to reporting info from the repository,'
                               'without arguments, show the list of followed '
                               'repositories',
        'show [signal]': 'show signal, without argument, shows the displayed '
                         'signals',
        'hide [signal]': 'hide the displayed signal, withour argument, show '
                         ' the list of hidden messages',
    }.get(command, "{0}quit, {0}lang=, {0}join, {0}follow, {0}show, {0}hide".format(COMMAND_PREFIX))

def color(n, msg):
    return '\x03{0:>02}{1}\x0300'.format(n, msg)

class Chan(object):
    def __init__(self, name):
        self.signals = DEFAULT_SIGNALS[:]
        self.repos = []
        self.name = name

    def load(self, data):
        self.name, repos, signals = data.split(';')
        self.repos = repos.split(',')
        self.signals = signals.split(',')

    def export(self):
        return '%s;%s;%s' % (self.name,
                             ','.join(self.repos),
                             ','.join(self.signals))


class KGB(SingleServerIRCBot):
    '''Main class, this is the bot that connect to irc and listen for commands
    '''

    _instance = None

    def __new__(cls, *args, **kw):
        if not KGB._instance:
            KGB._instance = SingleServerIRCBot.___new__(
                cls, *args, **kw)

        return cls._instance

    def __init__(self, *args, **kw):
        try:
            self.__singleton__
        except:
            SingleServerIRCBot.__init__(self, *args, **kw)
            self.__singleton__ = True

    def failsafe_start(self):
        try:
            print "before start"
            self.start()
            print "shouldn't be printed"
        except BaseException, e:
            self.save_state()
            raise

    def on_welcome(self, serv, event):
        ''' what to do when server is joined
        '''
        self.serv = serv
        serv.join('#KGB.vc')
        self.restore_state(serv)
        print self.serv
        print self.chans


    def save_state(self):
        '''save preferences for restart
        '''
        with open('chans', 'w') as conf_file:
            for chan in self.chans.values():
                conf_file.write(chan.export() + '\n')

    def restore_state(self, serv):
        ''' restore configuration (usually at restart)
        '''
        chan = Chan('#KGB.vc')
        self.chans = {'#KGB.vc': chan}
        with open('chans') as conf_file:
            for line in conf_file.readlines():
                chan = Chan('')
                chan.load(line.strip())
                self.chans[chan.name] = chan
                serv.join(chan.name)

    def is_command(self, message, name=None):
        if name:
            return message.startswith(COMMAND_PREFIX + name)
        else:
            return message.startswith(COMMAND_PREFIX)

    def on_pubmsg(self, serv, event):
        '''what to do when someone talk to me
        '''
        message = event.arguments()[0]

        if self.is_command(message):
            chan = self.chans[event.target()]

            if self.is_command(message, "help"):
                serv.notice(event.target(), usage(message.split(' ')[-1]))

            elif self.is_command(message, "join"):
                chan = message.split(' ')[-1]
                serv.join(chan)
                self.chans[chan] = Chan(chan)
                serv.notice(event.target(), "joined " + chan)

            elif self.is_command(message, "follow"):
                repos = message.split(' ')[1:]
                if not repos:
                    serv.notice(event.target(), ','.join(chan.repos))

                for repo in repos:
                    if repo in chan.repos:
                        serv.notice(event.target(),
                                    "%s already followed" % repo)
                    else:
                        chan.repos.append(repo)

                    serv.notice(event.target(), "done")

            elif self.is_command(message, "show"):
                signals = message.split(' ')[1:]
                if signals:
                    for signal in signals:
                        if signals in chan.signals:
                            serv.notice(event.target(),
                                        "%s already shown" % signal)

                        elif signal not in EXISTING_SIGNALS:
                            serv.notice(event.target(),
                                        "%s signal unknown" % signal)
                        else:
                            chan.signals.append(signal)

                else:
                    serv.notice(event.target(),
                                self.chans[event.target()].signals)

            elif self.is_command(message, "hide"):
                signals = message.split(' ')[1:]
                chan = self.chans[event.target()]

                if signals:
                    for signal in signals:
                        if signal not in EXISTING_SIGNALS:
                            serv.notice(event.target(),
                                        "%s signal unknown" % signal)
                        elif signal not in chan.signals:
                            serv.notice(event.target(),
                                        "%s already hidden" % signal)
                        else:
                            chan.signals.remove(signal)

                else:
                    # need to construct the list of hidden signals
                    signals = ','.join([
                        signal for signal in EXISTING_SIGNALS
                        if signal not in chan.signals])

                    serv.notice(event.target(), "hidden signals: %s" % signals)

            elif self.is_command(message, "quit"):
                serv.part(event.target(), "oh well…")

            else:
                serv.notice(event.target(), 'unknown command, see help')

    def render(self, signal, content):
        return ':'.join((signal, content))

    def notice(self, chan, repos, signal, content):
        self.serv.notice(chan.name, self.render(signal, content))

    def treat_signal(self, repos, signal, content):
        for chan in self.chans.values():
            if repos in chan.repos and signal in chan.signals:
                self.notice(chan, repos, signal, content)

    def get_short_url(self, url):
        if url in short_url_cache:
            return short_url_cache[url]
        req = requests.post('http://git.io/create',
                data={'url': url})
        if req.status_code != 200:
            return url
        surl = 'http://git.io/' + req.text
        short_url_cache[url] = surl
        return surl

    def shorten(self, text):
        text = text.replace('\n', '').replace('\r', '')
        if len(text) < 40:
            return text
        return text[:40] + '...'

    def treat_signal_hub(self, repos, signal, content):
        if signal == 'push':
            for commit in content['commits']:
                url = self.get_short_url(commit['url'])
                text = '{0} {1} {2} * {3} - {4}'.format(
                        color(COLOR_REPO, '[{0}]'.format(content['repository']['name'])),
                        color(COLOR_USER, commit['committer']['username']),
                        color(COLOR_BRANCH, content['ref'].split('/')[-1]),
                        self.shorten(commit['message']),
                        color(COLOR_URL, url))
                self.publish_message(repos, text)
        elif signal == 'issue_comment':
            if content['action'] != 'created':
                print 'got a comment, but not good action: ', content['action']
                return
            url = self.get_short_url(content['issue']['html_url'])
            text = '{0} {1} commented #{2} * {3} - {4}'.format(
                    color(COLOR_REPO, '[{0}]'.format(content['repository']['name'])),
                    color(COLOR_USER, content['comment']['user']['login']),
                    color(COLOR_ISSUE, content['issue']['number']),
                    self.shorten(content['comment']['body']),
                    color(COLOR_URL, url))
            self.publish_message(repos, text)
        elif signal == 'issues':
            if content['action'] in ('labeled', ):
                return
            url = self.get_short_url(content['issue']['html_url'])
            text = '{0} {1} {2} #{3} * {4} - {5}'.format(
                    color(COLOR_REPO, '[{0}]'.format(content['repository']['name'])),
                    color(COLOR_USER, content['issue']['user']['login']),
                    content['action'],
                    color(COLOR_ISSUE, content['issue']['number']),
                    self.shorten(content['issue']['title']),
                    color(COLOR_URL, url))
            self.publish_message(repos, text)
        else:
            print 'unknow signal ?', signal

    def publish_message(self, repos, text):
        print dir(self)
        for chan in self.chans.values():
            self.serv.privmsg(chan.name, text)


kgb = KGB(
    SERVERS,
    NICKNAME,
    'Show events from github')


#
# WEB part
#

app = Flask(__name__)

@app.route('/', methods=['POST', 'GET'])
def message():
    if request.method == 'GET':
        return ('''
            <html>
            <body>
            <form method="POST" action="/">
            <input name="repos"/>
            <input name="signal"/>
            <input name="message"/>
            <input type="submit"/>
            </form>
            </body>
            </html>
            ''')
    else:
        kgb.treat_signal(
            request.form['repos'],
            request.form['signal'],
            request.form['message'])
        return ''

@app.route('/event/<eventname>', methods=['POST'])
def pubsubhub(eventname):
    # cannot verify the signature yet, flask doesn't support to access to raw request data
    # when the mimetype is known
    payload = request.form['payload']
    #hashed = hmac.new(SECRET, payload, sha1)
    #signature = hashed.hexdigest()
    #print 'calculated signature', signature
    #print 'request signature', request.headers.get('X-Hub-Signature')
    #if request.headers.get('X-Hub-Signature') != signature:
    #    return abort(401)
    payload = loads(payload)
    from pprint import pprint
    print '------->', eventname
    pprint(payload)
    kgb.treat_signal_hub(
            payload['repository']['name'],
            eventname,
            payload)
    return ''

def main():
    #kgb.start()
    p = Thread(target=kgb.failsafe_start)
    p.daemon = True
    p.start()
    app.run(host='0.0.0.0', use_reloader=False)

def get_gh_credentials():
    print 'Username:',
    gh_user = raw_input()
    gh_password = getpass.getpass()
    return gh_user, gh_password

def install_hooks(repo, callback, mode='subscribe'):
    events = ('push', 'issues', 'issue_comment', 'commit_comment', 'pull_request')
    owner, repo = repo.split('/')
    gh_user, gh_password = get_gh_credentials()
    print 'Installing github hook for', owner, '/', repo, '...'
    for event in events:
        print ' ->', mode, 'to', event,
        data = {
                'hub.mode': mode,
                'hub.topic': 'https://github.com/{0}/{1}/events/{2}'.format(owner, repo, event),
                'hub.callback': callback + '/event/' + event,
                'hub.secret': SECRET }
        req = requests.post(
                'https://api.github.com/hub',
                data=data,
                auth=HTTPBasicAuth(gh_user, gh_password))
        print '({0})'.format(req.status_code)
        if req.text:
            print req.text

if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option('--watch', dest='watch',
            help='Name of the repo to watch in the format "user/repo"')
    parser.add_option('--unwatch', dest='unwatch',
            help='Name of the repo to unwatch in the format "user/repo"')
    parser.add_option('--callback', dest='callback',
            help='Callback of the pubsub hook. Something like http://myserver:5000/')
    options, args = parser.parse_args()

    if options.watch:
        if not options.callback:
            print 'Error: --watch need --callback'
            sys.exit(1)
        install_hooks(options.watch, options.callback, 'subscribe')
    elif options.unwatch:
        if not options.callback:
            print 'Error: --unwatch need --callback'
            sys.exit(1)
        install_hooks(options.unwatch, options.callback, 'unsubscribe')
    else:
        main()
