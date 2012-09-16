dht_bootstrapper
================

This python script will read a torrent file, look for a udp tracker, get a list of peers for that torrent and then gather a list of their IPs and DHT ports. This is useful for bootstrapping a DHT client

The first argument when running python dht.py is the torrent file:

python dht.py atorrent.torrent

