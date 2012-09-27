#!/usr/bin/env python
# coding: utf-8
'''
author: gabriel pettier
licence lgpl

require python-irclib
'''

from ircbot import SingleServerIRCBot

from flask import Flask, request
from threading import Thread
from random import randint

SERVERS = [('irc.freenode.net', 6667)]

NICKNAME = 'KGB-%s' % randint(64, 128)
COMMAND_PREFIX = '!'
EXISTING_SIGNALS = (
    'push,issue,commit_comment,pull_request,gollum,watch,'
    'download,fork,fork_apply,member,public,status').split(',')

DEFAULT_SIGNALS = (
    'push,issues,commit_comment,pull_request,fork_apply,member').split(',')


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
    }.get(command, "!quit, !lang=, !join, !follow, !show, !hide")


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
        except BaseException:
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
                self.chans[chan] = Chan()
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

kgb = KGB(
    SERVERS,
    NICKNAME,
    'show events from github')

'''
now the web part
'''
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


def main():
    #kgb.start()
    p = Thread(target=kgb.failsafe_start)
    p.daemon = True
    p.start()
    app.run(host='0.0.0.0', debug=True)


if __name__ == '__main__':
    main()
