import redis


def getlog(db, channel):
  log_order_key = 'log:{}'.format(channel)
  if not db.exists(log_order_key):
    return None
  log_order = db.lrange(log_order_key, 0, -1)
  
  log = []
  for evname in log_order:
    ev = db.hgetall(evname)
    if ev:
      log.append(ev)
  return log


event_formats = {
  'startlog': "=== Logging started",
  'endlog':   "=== Logging ended",
  'join':     "=== {source} joined the channel",
  'part':     "=== {source} left the channel ({message})",
  'quit':     "=== {source} quit IRC ({message})",
  'kick':     "=== {target} was kicked by {source} ({message})",
  'nick':     "=== {source} changed nick to {newnick}",
  'privmsg':  "<{source}> {message}",
  'action':   "* {source} {message}",
}

def printevent(ev):
  from datetime import datetime
  ts = datetime.fromtimestamp(int(ev['time']))
  timestring = ts.strftime("%Y-%m-%d %H:%M:%S")
  fmtstr = "({ts}) " + event_formats[ev['event']]
  print fmtstr.format(ts=timestring, **ev)

def printlog(log):
  for ev in reversed(log):
    printevent(ev)


def main():
  import config
  import sys

  db = redis.StrictRedis(**config.redis)
  if len(sys.argv) < 2:
    print "Usage: {} <channel>".format(sys.argv[0])
    sys.exit(255)
  print repr(sys.argv[1])
  log = getlog(db, sys.argv[1])
  if log:
    printlog(log)
  elif log is None:
    print "No log exists for that channel"
    sys.exit(1)
  else:
    print "Log for that channel is empty"

if __name__ == "__main__":
  main()
