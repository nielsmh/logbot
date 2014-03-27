import irc.bot
import irc.strings
import irc.dict
import redis
import random


class LogBot(irc.bot.SingleServerIRCBot):
  def __init__(self, config):
    self.config = config
    self.desired_channels = irc.dict.IRCDict((ch, True) for ch in config.channels)

    print "Connect to database"
    self.db = redis.StrictRedis(**config.redis)

    db_channels = self.db.lrange('channels', 0, -1)
    print "Loaded {} channels from config database".format(len(db_channels))
    self.desired_channels.update((ch, True) for ch in db_channels)
    print "Total {} channels to join".format(len(self.desired_channels))

    super(LogBot, self).__init__(config.servers, config.nick, config.realname)

  def save_config(self):
    self.db.delete('channels')
    self.db.lpush('channels', *self.desired_channels.keys())

  def on_nicknameinuse(self, conn, ev):
    new_nick = self.config.nick + random.randint(10, 99)
    print "Nick in use, instead trying {}".format(new_nick)
    conn.nick(new_nick)
    def reset_nick():
      print "Trying to switch to configured nick"
      conn.nick(self.config.nick)
    conn.execute_delayed(30, reset_nick)

  def get_version(self):
    return "Channel logger bot ({})".format(super(LogBot, self).get_version())

  def on_welcome(self, conn, ev):
    print "Connected!"
    for chan in self.desired_channels.keys():
      print "Join channel {}".format(chan)
      conn.join(chan)

  def on_invite(self, conn, ev):
    # join the channel invited to, and add it to the list of channels we want to be in
    if ev.target != conn.get_nickname():
      return
    channel = ev.arguments[0]
    self.desired_channels[channel] = True
    conn.join(channel)
    print "Invited to {} by {}".format(channel, ev.source)
    self.save_config()

  def on_kick(self, conn, ev):
    channel = ev.target
    kicked = ev.arguments[0]
    message = ev.arguments[1]
    if kicked == conn.get_nickname():
      del self.desired_channels[channel]
      print "Kicked from {} by {}".format(channel, ev.source)
      self.save_config()
    else:
      pass #TODO: log

  def on_privmsg(self, conn, ev):
    message = ev.arguments[0]
    conn.privmsg(ev.source.nick, "Hi {}, you said: {}".format(ev.source, message))
    #TODO: log


def main():
  try:
    import config
  except Exception as e:
    print "Could not import config"
    print e
    exit(1)

  bot = LogBot(config)
  try:
    bot.start()
  except KeyboardInterrupt:
    print "Now dying..."
    bot.save_config()
    bot.db.save()
    bot.connection.disconnect("Death by console")
    print "Dead."

if __name__ == "__main__":
  main()
