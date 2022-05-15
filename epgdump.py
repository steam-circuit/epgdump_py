#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import getopt

from constant import *
from parser import TransportStreamFile
from parser import parse_ts
from xmltv import *


def usage():
    print('''USAGE: epgdump.py -n CHANNEL_NAME -i INPUT_FILE -o OUTPUT_FILE
       epgdump.py -b -i INPUT_FILE -o OUTPUT_FILE
       epgdump.py -c -i INPUT_FILE -o OUTPUT_FILE
       epgdump.py -t -i INPUT_FILE -o OUTPUT_FILE
       epgdump.py [-b|-c|-t] -p TRANSPORT_STREAM_ID:SERVICE_ID:EVENT_ID -i INPUT_FILE
  -h, --help          print help message
  -b, --bs            input file is BS channel
  -c, --cs            input file is CS channel
  -t, --tb            input file is TB channel
  -n, --channel-name  specify channel identifier (e.g. ON TV JAPAN code)
  -d, --debug         parse all ts packet
  -f, --format        output formated xml with pprint (default: no space and no indent)
  -i, --input         specify ts file
  -o, --output        specify xml file
  -p, --print-time    print start time, and end time of specified id
  -e, --extra-info    output transport_stream_id, servece_id and event_id (not compliant with xmltv.dtd)
  -m, --max-packets   maximum ts packets of read
''', file=sys.stderr)

try:
    opts, args = getopt.getopt(sys.argv[1:], 'hbctn:dfi:o:p:em:', [
        'help', 'bs', 'cs', 'tb', 'channel-name=',
        'debug', 'format', 'input=', 'output=', 'print-time=', 'extra-info', 'max-packets'])
except (IndexError, getopt.GetoptError):
    usage()
    sys.exit(1)

channel_name = None
input_file = None
output_file = None
pretty_print = None
debug = False
b_type = TYPE_DIGITAL
transport_stream_id = None
service_id = None
event_id = None
output_extra_info = False
max_packets = None
for o,a in opts:
    if o in ('-h', '--help'):
        usage()
        sys.exit(0)
    elif o in ('-b', '--bs'):
        b_type = TYPE_BS
    elif o in ('-c', '--cs'):
        b_type = TYPE_CS
    elif o in ('-t', '--tb'):
        b_type = TYPE_TB
    elif o in ('-n', '--channel-name'):
        channel_name = a
    elif o in ('-d', '--debug'):
        debug = True
    elif o in ('-f', '--format'):
        pretty_print = PPRINT_INDENT_PREFIX
    elif o in ('-i', '--input'):
        input_file = a
    elif o in ('-o', '--output'):
        output_file = a
    elif o in ('-p', '--print-time'):
        arr = a.split(':')
        transport_stream_id = int(arr[0])
        service_id = int(arr[1])
        event_id = int(arr[2])
    elif o in ('-e', '--extra-info'):
        output_extra_info = True
    elif o in ('-m', '--max-packets'):
        max_packets = int(a)

if service_id == None and (
        (b_type == TYPE_DIGITAL and channel_name == None) or input_file == None or output_file == None):
    usage()
    sys.exit(1)
elif input_file == None:
    usage()
    sys.exit(1)

tsfile = TransportStreamFile(input_file, 'rb')
(service, events) = parse_ts(b_type, tsfile, max_packets, debug)
tsfile.close()
if service_id == None:
    create_xml(b_type, channel_name, service, events, output_file, pretty_print, output_extra_info)
else:
    start_time = None
    end_time = None
    for event in events:
        if (event.transport_stream_id == transport_stream_id and
            event.service_id == service_id and
            event.event_id == event_id):
            start_time = event.start_time
            end_time = event.start_time + event.duration
            break
    if start_time == None:
        print("not found: transport_stream_id=%d service_id=%d event_id=%d" %
                (transport_stream_id, service_id, event_id), file=sys.stderr)
        sys.exit(1)
    else:
        print(int(time.mktime(start_time.timetuple())),
                int(time.mktime(end_time.timetuple())))
