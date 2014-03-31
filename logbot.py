import irc.bot
import irc.strings
import irc.dict
import redis
import random
import hashlib
import time
import string


class LogBot(irc.bot.SingleServerIRCBot):
  def __init__(self, config):
    self.config = config
    self.desired_channels = irc.dict.IRCDict((ch, True) for ch in config.channels)

    print u"Connect to database"
    self.db = redis.StrictRedis(**config.redis)

    db_channels = self.db.lrange('cfg:channels', 0, -1)
    print u"Loaded {} channels from config database".format(len(db_channels))
    self.desired_channels.update((ch.decode('utf-8'), True) for ch in db_channels)
    print u"Total {} channels to join".format(len(self.desired_channels))

    super(LogBot, self).__init__(config.servers, config.nick, config.realname)

    # need to handle QUIT messages before the default bot handling,
    # so the nick is still registered on the channels for us to log
    self.connection.add_global_handler('quit', self.on_quit_prebot, -50)

    self.connection.execute_every(600, self.syncdb)

  def _connect(self):
    print u"Trying to connect to IRC server..."
    return super(LogBot, self)._connect()

  def save_config(self):
    self.db.delete('cfg:channels')
    self.db.lpush('cfg:channels', *[ch.encode('utf-8') for ch in self.desired_channels.keys()])

  def trimlog(self, channel):
    self.db.ltrim('log:{}'.format(channel.encode('utf-8')), 0, self.config.maxlogentries-1)

  def syncdb(self):
    print u"Performing database maintenance..."
    for ch in self.channels.keys():
      self.trimlog(ch)
    print u"Database maintenance done"

  def add_log(self, logdata, channels):
    # log the given data for the given list of channels
    logdata['time'] = str(int(time.time()))
    h = hashlib.md5()
    for k, v in logdata.iteritems():
      h.update(k.encode('utf-8'))
      h.update(v.encode('utf-8'))
    for c in channels:
      h.update(c.encode('utf-8'))
    evname = "evt:{}".format(h.digest())
    self.db.hmset(evname, logdata)
    self.db.expire(evname, self.config.expiretime)
    for ch in channels:
      self.db.lpush('log:{}'.format(ch.encode('utf-8')), evname)

  def make_log_read_token(self, nick, channel):
    token = ''.join(random.choice(string.ascii_letters) for i in range(7))
    dbkey = 'tkn:{}'.format(token)
    self.db.set(dbkey, channel)
    self.db.expire(dbkey, self.config.token_duration)
    return token

  def get_userchannels(self, usernick):
    return [chn for (chn, cho) in self.channels.iteritems() if cho.has_user(usernick)]

  def on_nicknameinuse(self, conn, ev):
    new_nick = self.config.nick + random.randint(10, 99)
    print u"Nick in use, instead trying {}".format(new_nick)
    conn.nick(new_nick)
    def reset_nick():
      print u"Trying to switch to configured nick"
      conn.nick(self.config.nick)
    conn.execute_delayed(30, reset_nick)

  def get_version(self):
    return u"Channel logger bot ({})".format(super(LogBot, self).get_version())

  def on_welcome(self, conn, ev):
    print u"Connected!"
    for chan in self.desired_channels.keys():
      print u"Join channel {}".format(chan)
      conn.join(chan)
    self.save_config()

  def on_invite(self, conn, ev):
    # join the channel invited to, and add it to the list of channels we want to be in
    if ev.target != conn.get_nickname():
      return
    channel = ev.arguments[0]
    self.desired_channels[channel] = True
    conn.join(channel)
    print u"Invited to {} by {}".format(channel, ev.source)
    self.save_config()

  def on_kick(self, conn, ev):
    channel = ev.target
    kicked = ev.arguments[0]
    message = ev.arguments[1]
    if kicked == conn.get_nickname():
      del self.desired_channels[channel]
      print u"Kicked from {} by {}".format(channel, ev.source)
      self.save_config()
      self.add_log({'event': 'endlog'}, [ev.target])
    else:
      logdata = {
        'event': 'kick',
        'source': ev.source,
        'target': ev.arguments[0],
        'message': ev.arguments[1] if len(ev.arguments) > 1 else '',
      }
      self.add_log(logdata, [ev.target])

  def on_nick(self, conn, ev):
    if ev.source.nick == conn.get_nickname() or ev.target == conn.get_nickname():
      # pretend we don't exist
      return
    logdata = {
      'event': 'nick',
      'source': ev.source,
      'newnick': ev.target,
    }
    self.add_log(logdata, self.get_userchannels(ev.target))

  def on_quit_prebot(self, conn, ev):
    if ev.source.nick == conn.get_nickname():
      return
    if ev.source.nick == self.config.nick:
      # someone using our desired nick left (maybe a ghost?)
      # reclaim it!
      conn.nick(self.config.nick)
      return
    logdata = {
      'event': 'quit',
      'source': ev.source,
      'message': ev.arguments[0] if len(ev.arguments) > 0 else '',
    }
    self.add_log(logdata, self.get_userchannels(ev.source.nick))

  def on_privmsg(self, conn, ev):
    message = ev.arguments[0].strip()
    can_admin = False
    if message.startswith(self.config.management_password):
      can_admin = True
      message = message[len(self.config.management_password):].strip()
    words = message.split()
    if len(words) > 0:
      command = words[0].lower()
      words = words[1:]
    else:
      command = 'help'

    if command == 'log':
      channels = self.get_userchannels(ev.source.nick)
      if len(words) >= 2:
        channels = [chn for chn in channels if chn in words[1:]]
      for chn in channels:
        token = self.make_log_read_token(ev.source.nick, chn)
        conn.privmsg(ev.source.nick, self.config.log_read_url_format.format(channel=chn, token=token))
    elif command == 'help':
      lines = [
        "Send me an IRC /invite to have me join and start logging a channel.",
        "To make me stop logging a channel, just /kick me from it.",
        "Other commands you can send me by private message:",
        "  LOG     Get a URL to read recent logs from the channels I'm in",
        "  HELP    Show this help message",
      ]
      if can_admin:
        lines += [
          "  INFO    Show information about channels I'm in, and my configuration",
          "  SAY     Takes arguments, first a target, then a message, delivers the message to the target"
          "  OP      Takes argument, a channel to rescue, only works when bot is the sole OP in channel"
        ]
      for l in lines:
        conn.privmsg(ev.source.nick, l)
    elif command == "info" and can_admin:
      print u"INFO from {}".format(ev.source)
      conn.privmsg(ev.source.nick, "Log expiry time: {} minutes".format(self.config.expiretime/60))
      conn.privmsg(ev.source.nick, "Max log length: {} entries".format(self.config.maxlogentries))
      conn.privmsg(ev.source.nick, "Currently logging the following channels:")
      for chn in self.desired_channels:
        conn.privmsg(ev.source.nick, u"  {}".format(chn))
    elif command == 'say' and can_admin:
      if len(words) < 2:
        conn.privmsg(ev.source.nick, "Usage: <password> SAY <target> <message>")
      else:
        print u"SAY {} from {}".format(words[0], ev.source)
        conn.privmsg(words[0], ' '.join(words[1:]))
    elif command == "op" and can_admin:
      if len(words) < 1:
        conn.privmsg(ev.source.nick, "Usage: <password> OP <channel>")
      elif not words[0] in self.channels:
        conn.privmsg(ev.source.nick, "Can't rescue {}, I'm not on that channel".format(words[0]))
      elif not self.channels[words[0]].is_oper(conn.get_nickname()):
        conn.privmsg(ev.source.nick, "Can't rescue {}, I'm not OP on that channel".format(words[0]))
      elif self.channels[words[0]].opers() != [conn.get_nickname()]:
        conn.privmsg(ev.source.nick, "Can't rescue {}, I'm not the sole OP on that channel".format(words[0]))
      else:
        print u"OP {} from {}".format(words[0], ev.source)
        conn.mode(words[0], '+o {}'.format(ev.source.nick))
        conn.privmsg(ev.source.nick, "Gave you OP on {}".format(words[0]))
    elif not can_admin and command in ['info', 'say', 'op']:
      conn.privmsg(ev.source.nick, "Sorry, you need to know the management password to use this command")

  def on_pubmsg(self, conn, ev):
    logdata = {
      'event': 'privmsg',
      'source': ev.source,
      'message': ev.arguments[0] if len(ev.arguments) > 0 else '',
    }
    self.add_log(logdata, [ev.target])

  def on_action(self, conn, ev):
    if not irc.client.is_channel(ev.target):
      return
    logdata = {
      'event': 'action',
      'source': ev.source,
      'message': ev.arguments[0] if len(ev.arguments) > 0 else '',
    }
    self.add_log(logdata, [ev.target])

  def on_join(self, conn, ev):
    if ev.source.nick == conn.get_nickname():
      # that's me!
      self.add_log({'event': 'startlog'}, [ev.target])
      return
    logdata = {
      'event': 'join',
      'source': ev.source,
    }
    self.add_log(logdata, [ev.target])

  def on_part(self, conn, ev):
    if ev.source.nick == conn.get_nickname():
      return
    logdata = {
      'event': 'part',
      'source': ev.source,
      'message': ev.arguments[0] if len(ev.arguments) > 0 else '',
    }
    self.add_log(logdata, [ev.target])

  def disconnect(self, message=''):
    self.add_log({'event': 'endlog'}, self.channels.keys())
    self.connection.disconnect(message)

def main():
  try:
    import config
  except Exception as e:
    print u"Could not import config"
    print e
    exit(1)

  bot = LogBot(config)
  try:
    bot.start()
  except KeyboardInterrupt:
    print "Now dying..."
    bot.save_config()
    bot.db.save()
    bot.disconnect(u"Death by console")
    print "Dead."

if __name__ == "__main__":
  main()
