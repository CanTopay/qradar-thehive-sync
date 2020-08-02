# qradar-thehive-sync
A cron type, script based integration for IBM QRadar and TheHive.
While playing around with theHive in my demo env.(community edt. of QRadar), I wrote this python script for a local cron based offense sync.
Also added some supporting libraries for Qradar calls, etc. Feel free to use, make better and share.

This package includes;
# qrhelper (Qradar Helper)
A tidy helper class for simplfying common ops on IBM QRadar.
https://github.com/CanTopay/qrhelper

# loghelper and sqlhelper
Well, I like helpers.
.An helper for logging.
.An helper for sqlite ops.

# thehive-playbook-creator
A script to dynamically create and assign SOP tasks(playbooks) to the cases.
https://github.com/CanTopay/thehive-playbook-creator
