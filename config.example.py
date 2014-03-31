servers = [
	('localhost', 6667),
]
channels = {
	"#test",
}
nick = "logbot"
realname = "Logger bot"
redis = dict(host='localhost', port=6379, db=0)
management_password = "password"
expiretime = 6*60*60  # 6 hours
maxlogentries = 200
log_read_url_format = u"http://logs.example.com/readlog?ch={channel}&tk={token}"
token_duration = 300  # 5 minutes
