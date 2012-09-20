import requests
from functools import partial
from bencode import bdecode, bencode
import hashlib, socket, array, time
from struct import *
import sys, re, random, thread, os, re
from cStringIO import StringIO

from tornado import ioloop
from tornado import iostream

MAX_PEERS_IN_REPLY = 1000
MIN_NUMBER_OF_DHT_BOOTSTRAP_PEERS = 5
DHT_LIST_CHECK_PERIOD_IN_MS = 500
HOW_LONG_TO_WAIT_FOR_DHT_PEERS = 10
#Tracker constants

ANNOUNCE = 1
STARTED = 2

#This just returns a random number between 0 and MAX 32 Bit Int
def gen_unsigned_32bit_id():
    return random.randint(0, 0xFFFFFFFF)
    
#This just returns a random unsigned int
def gen_signed_32bit_id():
    return random.randint(-2147483648, 2147483647)    
    
#Generates a string of 20 random bytes
def gen_peer_id():
    return ''.join(chr(random.randint(0,255)) for x in range(20))
    
def get_tracker_and_infohash_from_torrent(torrent_file):
    with open(torrent_file, "r") as tf:
        tdict = bdecode(tf.read())
        info_hash = hashlib.sha1( bencode( tdict['info'])).digest()
        an_groups = re.match("udp://(.*):(\d*)", tdict['announce'])
        
        if not an_groups:
            return None
                    
        return an_groups.group(1), an_groups.group(2), info_hash
        
def get_peer_list_from_tracker(tracker, port, peer_id, info_hash):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    transaction_id = gen_signed_32bit_id()
    connection_msg = pack(">qii", 
                        0x41727101980, #This will identify the protocol.
                        0,  #0 for a connection request
                        transaction_id #Randomized by client.
                        )
                        
    sock.sendto(connection_msg, (tracker, int(port)))
    data, addr = sock.recvfrom(1024)
    (action, returned_transaction_id, connection_id) = unpack(">iiq", data)
    assert( transaction_id == returned_transaction_id )
    
    announce_msg = ''.join((
        pack(">qii", 
            connection_id, 
            ANNOUNCE, 
            gen_signed_32bit_id()), #transaction_id used to figure out what response is for what request
            info_hash,
            peer_id,
        pack("qqqiIIiII",
            1, # bytes downloaded
            1, # bytes left to download 
            1,  # bytes uploaded
            STARTED, #Torrent event
            0, #IP address, if set to 0 use the requests ip
            gen_unsigned_32bit_id(), #A unique key that is randomized by the client.
            MAX_PEERS_IN_REPLY,  #The maximum number of peers you want in the reply. Use -1 for default.
            6889, #The port you're listening on.
            0 #Extensions
            )))

    sock.sendto(announce_msg, (tracker, int(port)))
    data, addr = sock.recvfrom(4096)
    data_buffer = StringIO(data)
    
    (action, returned_transaction_id, interval,
        leechers, seeders) = unpack(">iiiii", data_buffer.read(20))   
        
    num_peers_returned = (len(data) - 20) / 6
    
    torrent_peers = []
    for cur_peer in range(0, num_peers_returned):
        ip_bytes, port = unpack(">4sH",  data_buffer.read(6))
        host = '.'.join(map(str, map(ord, ip_bytes)))
        torrent_peers.append((host, port))
    
    return torrent_peers

        
class TorrentConnection(object):
    def __init__(self, stream, info_hash, peer_id, ip, dht_list):
        self.stream = stream
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.ip = ip
        self.dht_list = dht_list

    def send_handshake(self):
        handshake_msg = ''.join((
            pack(">B", 19),
            'BitTorrent protocol',
            chr(0) * 7,
            chr(1),
            self.info_hash,
            self.peer_id
            ))
            
        self.stream.write(handshake_msg)
        self.stream.read_bytes(68, self.get_first_msg_size)

    def get_first_msg_size(self, data):
        self.stream.read_bytes(4, self.got_msg_size)
        
    def got_msg_size(self, data):
        msg_size = unpack(">I", data)[0]
        self.stream.read_bytes(msg_size, self.got_msg_body)
    
    def got_msg_body(self, data):
        msg_type = unpack(">B",data[0])[0]
        
        if msg_type == 9:
            msg_type, dht_port = unpack(">BH",data)
            self.dht_list.append((self.ip, dht_port))
        self.stream.read_bytes(4, self.got_msg_size)
        
    def close(self):
        self.stream.close()
        
def get_peers_dht_port(torrent_peers, info_hash, peer_id, callback):
    dht_list = []
    torrent_connections = []
    io_loop = ioloop.IOLoop.instance()
    
    def check_dht_list_status(start_time):
        if len(dht_list) >= MIN_NUMBER_OF_DHT_BOOTSTRAP_PEERS or time.time() >= HOW_LONG_TO_WAIT_FOR_DHT_PEERS + start_time:
            io_loop.stop()

            for con in torrent_connections:
                con.close()
            
            callback(dht_list)
    
    for (cur_ip, cur_port) in torrent_peers:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        stream = iostream.IOStream(s)
        tc = TorrentConnection(stream, info_hash, peer_id, cur_ip, dht_list)
        stream.connect((cur_ip, cur_port), tc.send_handshake)
        torrent_connections.append(tc)
        
    periodic_dht_list_check = ioloop.PeriodicCallback(partial(check_dht_list_status, time.time()), DHT_LIST_CHECK_PERIOD_IN_MS, io_loop=io_loop)
    periodic_dht_list_check.start()
    io_loop.start()    
    
def get_dht_peers_from_torrent(torrent_file, callback):
    tracker, port, info_hash = get_tracker_and_infohash_from_torrent(torrent_file)
    #print "Info hash:%s" % info_hash
    peer_id = gen_peer_id()
    torrent_peers = get_peer_list_from_tracker(tracker, port, peer_id, info_hash)
    get_peers_dht_port(torrent_peers, info_hash, peer_id, callback)


def got_dht_peer(dht_list):
    print "Got a list of DHT IPS and Ports\n"
    print str(dht_list)
    
if __name__ == "__main__":
    get_dht_peers_from_torrent(sys.argv[1], got_dht_peer)

