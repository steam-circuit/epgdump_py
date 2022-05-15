# -*- coding: utf-8 -*-

import sys
import io
import array
import datetime
import copy
from functools import cmp_to_key

from constant import *
from aribtable import *
from aribstr import AribString


class TransportStreamFile(io.FileIO):
    def __iter__(self):
        return self
    def __next__(self):
        try:
            sync = self.read(1)
            while ord(sync) != 0x47:
                sync = self.read(1)
        except TypeError:
            raise StopIteration
        data = self.read(187)
        packet = array.array('B', data)
        packet.insert(0, ord(sync))
        if len(packet) != 188:
            raise StopIteration
        return packet

class TransportPacketParser:
    def __init__(self, tsfile, pid, max_packets, debug=False):
        self.tsfile = tsfile
        self.pid = pid
        self.section_map = {}
        self.queue = []
        self.debug = debug
        self.max_packets = max_packets if max_packets else READ_PACKETS_MAX
        self.count = 0
    def __iter__(self):
        return self
    def __next__(self):
        while True:
            try:
                return self.queue.pop(0)
            except IndexError:
                pass
            b_packet = self.tsfile.__next__()
            self.count += 1
            if not self.debug:
                if self.count >= self.max_packets:
                    raise StopIteration
            header = self.parse_header(b_packet)
            if header.pid in self.pid and header.adaptation_field_control == 1:
                while True:
                    (next_packet, section) = self.parse_section(header, self.section_map, b_packet)
                    if next_packet:
                        break
                    if section:
                        try:
                            t_packet = TransportPacket(header, section.data)
                            self.queue.append(t_packet)
                        except CRC32MpegError as e:
                            print('CRC32MpegError', e, file=sys.stderr)
                            self.section_map.pop(header.pid)
                            break

    def parse_header(self, b_packet):
        pid = ((b_packet[1] & 0x1F) << 8) + b_packet[2]
        payload_unit_start_indicator = ((b_packet[1] >> 6) & 0x01)
        adaptation_field_control = ((b_packet[3] >> 4) & 0x03)
        pointer_field = b_packet[4]
        return TransportPacketHeader(pid, payload_unit_start_indicator, adaptation_field_control, pointer_field)

    def parse_section(self, header, section_map, b_packet):
        sect = None
        next_packet = False
        sect = section_map.get(header.pid, Section())

        if header.payload_unit_start_indicator == 1:
            if sect.length_total == 0:
                section_length = 180
                if header.pointer_field > 179:
                    next_packet = True
                    sect = None
                else:
                    sect.idx += header.pointer_field
                    section_length -= header.pointer_field
                    sect.length_total = (((b_packet[sect.idx + 1] & 0x0F) << 8) + b_packet[sect.idx + 2]) # 12 uimsbf
                    if sect.length_total < 15:
                        next_packet = True
                        sect = None
                    elif sect.length_total <= section_length:
                        sect.data.extend(b_packet[sect.idx:sect.idx + 3 + sect.length_total])
                        sect.idx += sect.length_total + 3
                        sect.length_current += sect.length_total
                        section_map[header.pid] = sect
                        next_packet = False
                    else:
                        sect.data.extend(b_packet[sect.idx:])
                        sect.length_current += section_length
                        sect.idx = 5
                        section_map[header.pid] = sect
                        next_packet = True
                        sect = None
            else:
                remain = sect.length_total - sect.length_current
                section_length = 180 - sect.length_prev
                if remain == 0:
                    next_packet = True
                    section_map[header.pid] = Section()
                    section_header = 0
                    if sect.idx < 182:
                        if sect.length_prev:
                            prev = 3
                        else:
                            prev = 0
                        sect = Section(sect.idx + prev, sect.idx - 5 + prev)
                        section_header = (b_packet[sect.idx] << 16) + (b_packet[sect.idx + 1] << 8) + (b_packet[sect.idx + 2])
                        if section_header != 0xFFFFFF:
                            sect.length_total = (((b_packet[sect.idx + 1] & 0x0F) << 8) + b_packet[sect.idx + 2]) # 12 uimsbf
                            section_map[header.pid] = sect
                            next_packet = False
                    sect = None
                elif remain <= section_length:
                    sect.data.extend(b_packet[sect.idx:sect.idx + 3 + remain])
                    sect.idx += remain
                    sect.length_current += remain
                    section_map[header.pid] = sect
                    next_packet = False
                else:
                    sect.data.extend(b_packet[sect.idx:])
                    sect.length_current += section_length
                    sect.length_prev = 0
                    sect.idx = 5
                    section_map[header.pid] = sect
                    next_packet = True
                    sect = None
        else:
            # payload_unit_start_indicater set to 0b indicates that there is no pointer_field
            if sect.length_total != 0:
                sect.data.extend(b_packet[4:])
                sect.length_current += 184
                if sect.length_current >= sect.length_total:
                    section_map[header.pid] = Section()
                    next_packet = False
                else:
                    sect.length_prev = 0
                    sect = None
                    next_packet = True
            else:
                sect.length_prev = 0
                sect = None
                next_packet = True
        return (next_packet, sect)

def mjd2datetime(payload):
    mjd = (payload[0] << 8) | payload[1]
    yy_ = int((mjd - 15078.2) / 365.25)
    mm_ = int((mjd - 14956.1 - int(yy_ * 365.25)) / 30.6001)
    k = 1 if 14 <= mm_ <= 15 else 0
    day = mjd - 14956 - int(yy_ * 365.25) - int(mm_ * 30.6001)
    year = 1900 + yy_ + k
    month = mm_ - 1 - k * 12
    hour = ((payload[2] & 0xF0) >> 4) * 10 + (payload[2] & 0x0F)
    minute = ((payload[3] & 0xF0) >> 4) * 10 + (payload[3] & 0x0F)
    second = ((payload[4] & 0xF0) >> 4) * 10 + (payload[4] & 0x0F)
    try:
        return datetime.datetime(year, month, day, hour, minute, second)
    except ValueError:
        return datetime.datetime(9999, 1, 1, 1, 1, 1)

def bcd2time(payload):
    hour = ((payload[0] & 0xF0) >> 4) * 10 + (payload[0] & 0x0F)
    minute = ((payload[1] & 0xF0) >> 4) * 10 + (payload[1] & 0x0F)
    second = ((payload[2] & 0xF0) >> 4) * 10 + (payload[2] & 0x0F)
    return datetime.timedelta(hours=hour, minutes=minute, seconds=second)

def parseShortEventDescriptor(idx, event, t_packet, b_packet):
    descriptor_tag = b_packet[idx]        # 8   uimsbf
    descriptor_length = b_packet[idx + 1] # 8   uimsbf
    ISO_639_language_code = (
            chr(b_packet[idx + 2]) +
            chr(b_packet[idx + 3]) +
            chr(b_packet[idx + 4]))       # 24 bslbf
    event_name_length = b_packet[idx + 5] # 8 uimsbf
    arib = AribString(b_packet[idx + 6:idx + 6 + event_name_length])
    event_name = arib.convert_utf()
    idx = idx + 6 + event_name_length
    text_length = b_packet[idx]           # 8 uimsbf
    arib = AribString(b_packet[idx + 1:idx + 1 + text_length])
    text = arib.convert_utf()
    desc = ShortEventDescriptor(descriptor_tag, descriptor_length,
            ISO_639_language_code, event_name_length, event_name,
            text_length, text)
    event.descriptors.append(desc)

def parseExtendedEventDescriptor(idx, event, t_packet, b_packet):
    descriptor_tag = b_packet[idx]        # 8 uimsbf
    descriptor_length = b_packet[idx + 1] # 8 uimsbf
    descriptor_number = (b_packet[idx + 2] >> 4)        # 4 uimsbf
    last_descriptor_number = (b_packet[idx + 2] & 0x0F) # 4 uimsbf
    ISO_639_language_code = (
            chr(b_packet[idx + 3]) +
            chr(b_packet[idx + 4]) +
            chr(b_packet[idx + 5]))       # 24 bslbf
    length_of_items = b_packet[idx + 6]   # 8 uimsbf
    idx = idx + 7
    length = idx + length_of_items
    item_list = []
    while idx < length:
        item_description_length = b_packet[idx] # 8 uimsbf
        item_description = b_packet[idx + 1:idx + 1 + item_description_length]
        idx = idx + 1 + item_description_length
        item_length = b_packet[idx]             # 8 uimsbf
        item = b_packet[idx + 1:idx + 1 + item_length]
        item_list.append(Item(item_description_length, item_description,
            item_length, item))
        idx = idx + 1 + item_length
    text_length = b_packet[idx] # 8 uimsbf
    arib = AribString(b_packet[idx + 1:idx + 1 + text_length])
    text = arib.convert_utf()
    desc = ExtendedEventDescriptor(descriptor_tag, descriptor_length,
            descriptor_number, last_descriptor_number, ISO_639_language_code,
            length_of_items, item_list, text_length, text)
    event.descriptors.append(desc)

def parseContentDescriptor(idx, event, t_packet, b_packet):
    descriptor_tag = b_packet[idx]        # 8 uimsbf
    descriptor_length = b_packet[idx + 1] # 8 uimsbf
    idx += 2
    length = idx + descriptor_length
    content_list = []
    while idx < length:
        content_nibble_level_1 = (b_packet[idx] >> 4)   # 4 uimsbf
        content_nibble_level_2 = (b_packet[idx] & 0x0F) # 4 uimsbf
        user_nibble_1 = (b_packet[idx + 1] >> 4)        # 4 uimsbf
        user_nibble_2 = (b_packet[idx + 1] & 0x0F)      # 4 uimsbf
        content = ContentType(content_nibble_level_1, content_nibble_level_2,
                user_nibble_1, user_nibble_2)
        content_list.append(content)
        idx += 2
    desc = ContentDescriptor(descriptor_tag, descriptor_length, content_list)
    event.descriptors.append(desc)

def parseServiceDescriptor(idx, service, t_packet, b_packet):
    descriptor_tag = b_packet[idx]        # 8 uimsbf
    descriptor_length = b_packet[idx + 1] # 8 uimsbf
    service_type = b_packet[idx + 2]      # 8 uimsbf
    service_provider_name_length = b_packet[idx + 3] # 8 uimsbf
    arib = AribString(b_packet[idx + 4:idx + 4 + service_provider_name_length])
    service_provider_name = arib.convert_utf()
    idx = idx + 4 + service_provider_name_length
    service_name_length = b_packet[idx]   # 8 uimsbf
    arib = AribString(b_packet[idx + 1:idx + 1 + service_name_length])
    service_name = arib.convert_utf()
    sd = ServiceDescriptor(descriptor_tag, descriptor_length, service_type,
            service_provider_name_length, service_provider_name,
            service_name_length, service_name)
    service.descriptors.append(sd)

def parseDescriptors(idx, table, t_packet, b_packet):
    iface = {
            TAG_SED:parseShortEventDescriptor,
            TAG_EED:parseExtendedEventDescriptor,
            TAG_CD :parseContentDescriptor,
            TAG_SD :parseServiceDescriptor}
    length = idx + table.descriptors_loop_length
    while idx < length:
        descriptor_tag = b_packet[idx]        # 8   uimsbf
        descriptor_length = b_packet[idx + 1] # 8   uimsbf
        if descriptor_tag in iface.keys():
            iface[descriptor_tag](idx, table, t_packet, b_packet)
        idx = idx + 2 + descriptor_length

def parseEvents(t_packet, b_packet):
    idx = 19
    length = t_packet.eit.section_length - idx
    while idx < length:
        event_id = (b_packet[idx] << 8) + b_packet[idx + 1]   # 16  uimsbf
        start_time = mjd2datetime(b_packet[idx + 2 :idx + 7]) # 40  bslbf
        duration = bcd2time(b_packet[idx + 7:idx + 10])       # 24  uimsbf
        running_status = (b_packet[idx + 10] >> 5)            # 3   uimsbf
        free_CA_mode = ((b_packet[idx + 10] >> 4) & 0x01)     # 1   bslbf
        descriptors_loop_length = ((b_packet[idx + 10] & 0x0F) << 8) + b_packet[idx + 11] # 12  uimsbf
        event = Event(t_packet.eit.original_network_id,
                t_packet.eit.transport_stream_id, t_packet.eit.service_id, event_id,
                start_time, duration, running_status, free_CA_mode, descriptors_loop_length)
        parseDescriptors(idx + 12, event, t_packet, b_packet)
        t_packet.eit.events.append(event)
        idx = idx + 12 + descriptors_loop_length

def parseService(t_packet, b_packet):
    idx = 16
    length = t_packet.sdt.section_length - idx
    while idx < length:
        service_id = (b_packet[idx] << 8) + b_packet[idx + 1] # 16 uimsbf
        # reserved_future_use 3 bslbf
        EIT_user_defined_flags = ((b_packet[idx + 2] >> 2) & 0x07) # 3 bslbf
        EIT_schedule_flag = ((b_packet[idx + 2] >> 1) & 0x01)      # 1 bslbf
        EIT_present_following_flag = (b_packet[idx + 2] & 0x01)          # 1 bslbf
        running_status = ((b_packet[idx + 3] >> 5) & 0x03)               # 3 uimsbf
        free_CA_mode = ((b_packet[idx + 3] >> 4) & 0x01)                 # 1 bslbf
        descriptors_loop_length = (((b_packet[idx + 3] & 0x0F) << 8) + b_packet[idx + 4]) # 12 uimsbf
        service = Service(service_id, EIT_user_defined_flags, EIT_schedule_flag,
                EIT_present_following_flag, running_status, free_CA_mode,
                descriptors_loop_length)
        parseDescriptors(idx + 5, service, t_packet, b_packet)
        t_packet.sdt.services.append(service)
        idx = idx + 5 + descriptors_loop_length

def add_event(b_type, event_map, t_packet):
    for event in t_packet.eit.events:
        if b_type == TYPE_DIGITAL:
            m_id = event.event_id
        else:
            m_id = (event.transport_stream_id << 32) + (event.service_id << 16) + event.event_id
        master = event_map.get(m_id)
        if master == None:
            master = copy.copy(event)
            master.descriptors = None
            event_map[m_id] = master
        elif event.service_id < master.service_id:
            master.service_id = event.service_id
        for desc in event.descriptors:
            tag = desc.descriptor_tag
            if tag == TAG_SED:
                master.desc_short = desc
            elif tag == TAG_CD:
                master.desc_content = desc
            elif tag == TAG_EED:
                if master.desc_extended == None:
                    master.desc_extended = desc.items
                else:
                    master.desc_extended.extend(desc.items)

def fix_events(events):
    event_list = []
    for event in events:
        item_list = []
        item_map = {}
        if event.desc_short == None:
            continue
        if event.desc_extended != None:
            for item in event.desc_extended:
                if item.item_description_length == 0:
                    item_list[-1].item.extend(item.item)
                    item_list[-1].item_length += item.item_length
                else:
                    item_list.append(item)
            for item in item_list:
                arib = AribString(item.item_description)
                item.item_description = arib.convert_utf()
                arib = AribString(item.item)
                item.item = arib.convert_utf()
            for item in item_list:
                item_map[item.item_description] = item.item
            event.desc_extended = item_map
        event_list.append(event)
    return event_list

def compare_event(x, y):
        return int((x.start_time - y.start_time).total_seconds())

def compare_service(x, y):
    service_id = x.service_id - y.service_id
    if service_id == 0:
        return int((x.start_time - y.start_time).total_seconds())
    else:
        return service_id

def parse_eit(b_type, service, tsfile, max_packets, debug):
    # Event Information Table
    ids = service.keys()
    event_map = {}
    parser = TransportPacketParser(tsfile, EIT_PID, max_packets, debug)
    for t_packet in parser:
        if t_packet.eit.service_id in ids:
            parseEvents(t_packet, t_packet.binary_data)
            add_event(b_type, event_map, t_packet)
    print("EIT: %i packets read" % (parser.count), file=sys.stderr)
    event_list = list(event_map.values())
    if b_type == TYPE_DIGITAL:
        event_list = sorted(event_list, key=cmp_to_key(compare_event))
    else:
        event_list = sorted(event_list, key=cmp_to_key(compare_service))
    event_list = fix_events(event_list)
    return event_list

def parse_sdt(b_type, tsfile, max_packets, debug):
    # Service Description Table
    service_map = {}
    parser = TransportPacketParser(tsfile, SDT_PID, max_packets, debug)
    for t_packet in parser:
        parseService(t_packet, t_packet.binary_data)
        for service in t_packet.sdt.services:
            if (service.EIT_schedule_flag == 1 and
                    service.EIT_present_following_flag == 1 and
                    service.descriptors[0].service_type in ACCEPT_SERVICE_TYPE):
                service_map[service.service_id] = service.descriptors[0].service_name
        if b_type == TYPE_DIGITAL:
            break
    print("SDT: %i packets read" % (parser.count), file=sys.stderr)
    return service_map

def parse_ts(b_type, tsfile, max_packets, debug):
    service = parse_sdt(b_type, tsfile, max_packets, debug)
    tsfile.seek(0)
    events = parse_eit(b_type, service, tsfile, max_packets, debug)
    return (service, events)
