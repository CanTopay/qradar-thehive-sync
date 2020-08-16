# qradar-thehive-sync
A cron job based, old school integration type for IBM QRadar and The Hive.
While playing around with theHive in my demo env.(community edt. QRadar), I wrote this python script for offense syncs.
Feel free to use, make better and share.

I also include some supporting libraries(my helpers), for Qradar calls, sqlite db operations, logging  etc.

So, this package includes:
# qrhelper (Qradar Helper)
A tidy helper class for simplfying common ops on IBM QRadar.
https://github.com/CanTopay/qrhelper

# loghelper and sqlhelper
Well, I like helpers.
.An helper for logging.
.An helper for sqlite ops.

If you also have an interest for automating SOP task assignments (exp. using QRadar Rule groups), have a look at below sample script.
# thehive-playbook-creator 
A script to dynamically create and assign tasks(SOP playbooks) into the case.
https://github.com/CanTopay/thehive-playbook-creator

Requirements:
- Install Python 3 and then just pip the thehive4py, keyring, sqlite3, json.(Check the imports)
   