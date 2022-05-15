# -*- coding: utf-8 -*-

from datetime import datetime

import re

import xml.etree.ElementTree as ET
import xml.dom.minidom as MD

from constant import *


def regain_width(text):
    if text is None:
        return
    text = re.sub(r'　([\x20-\x7e])', " \\1", text)
    text = re.sub(r'([^\x20-\x7e\uFF61-\uFF9F])!', "\\1！", text)
    text = re.sub(r'([^\x20-\x7e\uFF61-\uFF9F])\?', "\\1？", text)
    return text

def get_text(text):
    if text != None:
        if isinstance(text, bytes):
            return text.decode('utf-8')
        else:
            return text
    else:
        return ""

def create_xml(b_type, channel_name, service, events, filename, pretty_print, output_extra_info):
    channel_el_list = create_channel(b_type, channel_name, service)
    programme_el_list = create_programme(channel_name, events, b_type, output_extra_info)
    create_datetime = datetime.now().strftime(TIMESTAMP_FORMAT)
    attr = {'date':create_datetime,
            'generator-info-name':GENERATOR_INFO_NAME,
            'generator-info-url':GENERATOR_INFO_URL}
    tv_el = ET.Element('tv', attr)

    for el in channel_el_list:
        tv_el.append(el)
    for el in programme_el_list:
        tv_el.append(el)

    fd = open(filename, 'wb')
    if pretty_print is not None and pretty_print != '':
        xml_str = ET.tostring(tv_el)
        xml_str = MD.parseString(xml_str).toprettyxml(indent=pretty_print, encoding='utf-8')
        fd.write(xml_str)
    else:
        ET.ElementTree(tv_el).write(fd, encoding='utf-8')
    fd.close()

def create_channel(b_type, channel_name, service):
    el_list = []
    for (service_id, service_name) in service.items():
        channel_id = b_type + str(service_id)
        attr = {'id':channel_id}
        if channel_name != None:
            attr['name'] = channel_name
        channel_el = ET.Element('channel', attr)
        attr = {'lang':'ja'}

        display_el = ET.Element('display-name', attr)
        display_el.text = get_text(service_name)
        channel_el.append(display_el)

        display_el = ET.Element('display-name', attr)
        display_el.text = channel_id
        channel_el.append(display_el)

        display_el = ET.Element('display-name', attr)
        display_el.text = channel_id + ' ' + get_text(service_name)
        channel_el.append(display_el)

        el_list.append(channel_el)

    return el_list

def create_programme(channel_name, events, b_type, output_extra_info):
    el_list = []
    for event in events:
        channel_id = b_type + str(event.service_id)
        start = event.start_time.strftime(TIMESTAMP_FORMAT)
        stop = (event.start_time + event.duration).strftime(TIMESTAMP_FORMAT)
        attr = {'start':start, 'stop':stop, 'channel':channel_id}
        programme_el = ET.Element('programme', attr)

        attr = {'units':'minutes'}
        length_el = ET.Element('length', attr)
        length_el.text = str(event.duration.seconds // 60)
        programme_el.append(length_el)

        title_text = regain_width(event.desc_short.event_name)
        attr = {'lang':'ja'}
        title_el = ET.Element('title', attr)
        title_el.text = get_text(title_text)
        programme_el.append(title_el)

        sed_text = ''
        if event.desc_short.text is not None:
            sed_text = regain_width(event.desc_short.text.strip())
        if sed_text != '':
            attr = {'lang':'ja'}
            sed_el = ET.Element('desc', attr)
            sed_el.text = get_text(sed_text)
            programme_el.append(sed_el)

        # this element is not compliant with xmltv.dtd (but very informative)
        if event.desc_content != None:
            for ct in event.desc_content.content_type_array:
                content_nibble_set = (ct.content_nibble_level_1 << 4) + ct.content_nibble_level_2
                user_nibble_set = (ct.user_nibble_1 << 4) + ct.user_nibble_2
                content_nibble_level_1_text = 'UNKNOWN'
                content_nibble_level_2_text = 'UNKNOWN'
                try:
                    c_map = CONTENT_TYPE[ct.content_nibble_level_1]
                    content_nibble_level_1_text = c_map[0]
                    content_nibble_level_2_text = c_map[1][ct.content_nibble_level_2]
                except KeyError:
                    pass
                attr = {'content-nibble-set':str(content_nibble_set),
                        'user-nibble-set':str(user_nibble_set),
                        'lang':'ja'}
                category_text = get_text(content_nibble_level_1_text)
                category_text += ' > ' + get_text(content_nibble_level_2_text)
                desc_content_el = ET.Element('category', attr)
                desc_content_el.text = category_text
                programme_el.append(desc_content_el)

        # this element is not compliant with xmltv.dtd (but very informative)
        if output_extra_info == True:
            extra_info_el = ET.Element('extra-info')
            el = ET.Element('transport-stream-id')
            el.text = str(event.transport_stream_id)
            extra_info_el.append(el)
            el = ET.Element('original-network-id')
            el.text = str(event.original_network_id)
            extra_info_el.append(el)
            el = ET.Element('service-id')
            el.text = str(event.service_id)
            extra_info_el.append(el)
            el = ET.Element('event-id')
            el.text = str(event.event_id)
            extra_info_el.append(el)

            eed_text = ''
            if event.desc_extended is not None:
                for (k,v) in event.desc_extended.items():
                    item_name = k.strip()
                    item_value = regain_width(v.strip())
                    eed_text += '《' + item_name + '》\n' + item_value + '\n\n'
            if eed_text != '':
                attr = {'lang':'ja'}
                el = ET.Element('extended-event-descriptor', attr)
                el.text = get_text(eed_text.rstrip())
                extra_info_el.append(el)

            programme_el.append(extra_info_el)

        el_list.append(programme_el)

    return el_list
