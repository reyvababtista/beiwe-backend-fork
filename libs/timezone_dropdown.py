from dateutil import tz
import pytz
from datetime import timedelta
from collections import defaultdict


def timedelta_to_label(td: timedelta) -> str:
    """ returns a string like +1:00 """
    label = "-" + str(abs(td)) if td.total_seconds() < 0 else "+" + str(abs(td))
    return label[:-3]


def string_sorter(key: str):
    """ get the first timedelta's floating point representation as the 'key' in our sort algo."""
    return float(key.split("/")[0].replace(":", "."))


def build_dictionary_of_timezones():
    # defaultdicts are cool.
    zones_by_offset = defaultdict(list)

    # there are more timezones in pytz.all_timezones
    for zone_name in pytz.common_timezones:
        # this 'tz_info' variable's type may be dependent on your platform, which is ... just insane.
        # This has been tested and works on Ubuntu and AWS Linux 1.
        tz_info: tz.tzfile = tz.gettz(zone_name)
        utc_offset: timedelta = tz_info._ttinfo_std.delta

        # No DST case
        if tz_info._ttinfo_dst is None:
            label = timedelta_to_label(utc_offset)
        else:
            dst_offset = tz_info._ttinfo_dst.delta
            # fun timezone case: some timezones HAD daylight savings in the past, but not anymore.
            # treat those as not having dst because anything else is madness.
            if dst_offset == utc_offset:
                label = timedelta_to_label(utc_offset)
            else:
                # this ordering yields +4:00/+5:00 ordering in most cases, but there are exceptions?
                # It's not hemispheric, I don't what those places are doing with time.
                label = f"{timedelta_to_label(utc_offset)}/{timedelta_to_label(dst_offset)}"

        zones_by_offset[label].append(zone_name)

    and_finally_sorted = {}
    for offset in sorted(zones_by_offset, key=string_sorter):
        and_finally_sorted[offset] = zones_by_offset[offset]

    return and_finally_sorted


def condense_offsets(all_zones_by_offset):
    final_ret = []

    for offset_numbers, locations in all_zones_by_offset.items():
        locations.sort()  # should already be sorted...?
        all_names_condensed = []

        doubles = defaultdict(set)
        # most are of the form "America/New_York", but some are America/North_Dakota/Beulah, and
        # some are just "UTC
        for splits in (l.split("/") for l in locations):

            # only the 1 thing, this can go right in
            if len(splits) == 1:
                all_names_condensed.append(splits[0])
                continue

            # cases: 2+ things, we don't care about anything past the first suffix those are insane.
            prefix, suffix = splits[0], splits[1]
            doubles[prefix].add(suffix)

        for prefix, suffices in doubles.items():
            suffices = list(suffices)
            suffices.sort()
            some_names_condensed = prefix + " - " + "/".join(suffices)
            all_names_condensed.append(some_names_condensed)

        #
        if len(all_names_condensed) == 1:
            all_names_condensed = [all_names_condensed[0].replace(" - ", "/")]

        final_ret.append((offset_numbers, "\n"
                                          "".join(all_names_condensed),))
    return final_ret


# ALL_TIMEZONES_DROPDOWN = condense_offsets(build_dictionary_of_timezones())
# the code above generates this data structure (February 2021:
ALL_TIMEZONES_DROPDOWN = [
    ('-11:00', 'Pacific/Midway/Niue/Pago_Pago'),
    ('-10:00/-9:00', 'America/Adak'),
    ('-10:00/-9:30', 'Pacific - Honolulu/Rarotonga\n'
                     'US - Hawaii'),
    ('-10:00', 'Pacific/Tahiti'),
    ('-9:30', 'Pacific/Marquesas'),
    ('-9:00/-8:00', 'America - Anchorage/Juneau/Metlakatla/Nome/Sitka/Yakutat\n'
                    'US - Alaska'),
    ('-9:00', 'Pacific/Gambier'),
    ('-8:00/-7:00', 'America - Los_Angeles/Tijuana/Vancouver\n'
                    'Canada - Pacific\n'
                    'US - Pacific'),
    ('-8:00', 'Pacific/Pitcairn'),
    ('-7:00/-6:00', 'America - Boise/Cambridge_Bay/Chihuahua/Denver/Edmonton/Hermosillo/Inuvik/Mazatlan/Ojinaga/Phoenix/Yellowknife\n'
                    'Canada - Mountain\n'
                    'US - Arizona/Mountain'),
    ('-7:00', 'America/Creston/Dawson/Dawson_Creek/Fort_Nelson/Whitehorse'),
    ('-6:00/-5:00', 'America - Bahia_Banderas/Belize/Chicago/Costa_Rica/El_Salvador/Guatemala/Indiana/Managua/Matamoros/Menominee/Merida/Mexico_City/Monterrey/North_Dakota/Rainy_River/Rankin_Inlet/Resolute/Tegucigalpa/Winnipeg\n'
                    'Canada - Central\n'
                    'Pacific - Easter/Galapagos\n'
                    'US - Central'),
    ('-6:00', 'America/Regina/Swift_Current'),
    ('-5:00', 'America/Atikokan/Cancun/Cayman/Panama'),
    ('-5:00/-4:00', 'America - Bogota/Detroit/Eirunepe/Grand_Turk/Guayaquil/Havana/Indiana/Iqaluit/Jamaica/Kentucky/Lima/Nassau/New_York/Nipigon/Pangnirtung/Port-au-Prince/Rio_Branco/Thunder_Bay/Toronto\n'
                    'Canada - Eastern\n'
                    'US - Eastern'),
    ('-4:00', 'America/Anguilla/Antigua/Aruba/Caracas/Curacao/Dominica/Grenada/Guadeloupe/Guyana/Kralendijk/Lower_Princes/Marigot/Montserrat/Port_of_Spain/St_Barthelemy/St_Kitts/St_Lucia/St_Thomas/St_Vincent/Tortola'),
    ('-4:00/-3:00', 'America - Asuncion/Barbados/Blanc-Sablon/Boa_Vista/Campo_Grande/Cuiaba/Glace_Bay/Goose_Bay/Halifax/Manaus/Martinique/Moncton/Porto_Velho/Puerto_Rico/Santiago/Thule\n'
                    'Atlantic - Bermuda\n'
                    'Canada - Atlantic'),
    ('-4:00/-3:32', 'America/La_Paz'),
    ('-4:00/-4:30', 'America/Santo_Domingo'),
    ('-3:30/-2:30', 'America - St_Johns\n'
                    'Canada - Newfoundland'),
    ('-3:00/-2:00', 'America/Araguaina/Argentina/Bahia/Belem/Fortaleza/Maceio/Miquelon/Montevideo/Nuuk/Recife/Sao_Paulo'),
    ('-3:00', 'America - Argentina/Cayenne/Paramaribo/Punta_Arenas/Santarem\n'
              'Antarctica - Palmer/Rothera\n'
              'Atlantic - Stanley'),
    ('-2:00/-1:00', 'America/Noronha'),
    ('-2:00', 'Atlantic/South_Georgia'),
    ('-1:00/+0:00', 'America - Scoresbysund\n'
                    'Atlantic - Azores'),
    ('-1:00', 'Atlantic/Cape_Verde'),
    ('+0:00', 'GMT\n'
              'UTC\n'
              'Africa - Abidjan/Bamako/Banjul/Bissau/Conakry/Dakar/Freetown/Lome/Monrovia/Nouakchott/Ouagadougou/Sao_Tome\n'
              'Atlantic - Reykjavik/St_Helena'),
    ('+0:00/+0:30', 'Africa/Accra'),
    ('+0:00/-2:00', 'America/Danmarkshavn'),
    ('+0:00/+2:00', 'Antarctica/Troll'),
    ('+0:00/+1:00', 'Atlantic - Canary/Faroe/Madeira\n'
                    'Europe - Guernsey/Isle_of_Man/Jersey/Lisbon/London'),
    ('+1:00', 'Africa/Algiers/Bangui/Brazzaville/Douala/Kinshasa/Lagos/Libreville/Luanda/Malabo/Niamey/Porto-Novo'),
    ('+1:00/+0:00', 'Africa - Casablanca/El_Aaiun\n'
                    'Europe - Dublin'),
    ('+1:00/+2:00', 'Africa - Ceuta/Ndjamena/Tunis\n'
                    'Arctic - Longyearbyen\n'
                    'Europe - Amsterdam/Andorra/Belgrade/Berlin/Bratislava/Brussels/Budapest/Busingen/Copenhagen/Gibraltar/Ljubljana/Luxembourg/Madrid/Malta/Monaco/Oslo/Paris/Podgorica/Prague/Rome/San_Marino/Sarajevo/Skopje/Stockholm/Tirane/Vaduz/Vatican/Vienna/Warsaw/Zagreb/Zurich'),
    ('+2:00', 'Africa/Blantyre/Bujumbura/Gaborone/Harare/Kigali/Lubumbashi/Lusaka/Maputo/Tripoli'),
    ('+2:00/+3:00', 'Africa - Cairo/Johannesburg/Juba/Khartoum/Maseru/Mbabane\n'
                    'Asia - Amman/Beirut/Damascus/Famagusta/Gaza/Hebron/Jerusalem/Nicosia\n'
                    'Europe - Athens/Bucharest/Chisinau/Helsinki/Kaliningrad/Kiev/Mariehamn/Riga/Sofia/Tallinn/Uzhgorod/Vilnius/Zaporozhye'),
    ('+2:00/+1:00', 'Africa/Windhoek'),
    ('+3:00', 'Africa - Addis_Ababa/Asmara/Dar_es_Salaam/Djibouti/Kampala/Mogadishu/Nairobi\n'
              'Antarctica - Syowa\n'
              'Asia - Aden/Bahrain/Kuwait/Qatar/Riyadh\n'
              'Europe - Istanbul/Minsk/Simferopol\n'
              'Indian - Antananarivo/Comoro/Mayotte'),
    ('+3:00/+4:00', 'Asia - Baghdad\n'
                    'Europe - Kirov/Moscow/Volgograd'),
    ('+3:30/+4:30', 'Asia/Tehran'),
    ('+4:00/+5:00', 'Asia - Baku/Yerevan\n'
                    'Indian - Mauritius'),
    ('+4:00', 'Asia - Dubai/Muscat/Tbilisi\n'
              'Europe - Astrakhan/Samara/Saratov/Ulyanovsk\n'
              'Indian - Mahe/Reunion'),
    ('+4:30', 'Asia/Kabul'),
    ('+5:00', 'Antarctica - Mawson\n'
              'Asia - Aqtau/Ashgabat/Atyrau/Oral\n'
              'Indian - Kerguelen/Maldives'),
    ('+5:00/+6:00', 'Asia/Aqtobe/Dushanbe/Karachi/Qyzylorda/Samarkand/Tashkent/Yekaterinburg'),
    ('+5:30/+6:30', 'Asia/Colombo/Kolkata'),
    ('+5:45', 'Asia/Kathmandu'),
    ('+6:00', 'Antarctica - Vostok\n'
              'Asia - Bishkek/Qostanay/Thimphu/Urumqi\n'
              'Indian - Chagos'),
    ('+6:00/+7:00', 'Asia/Almaty/Dhaka/Omsk'),
    ('+6:30', 'Asia - Yangon\n'
              'Indian - Cocos'),
    ('+7:00', 'Antarctica - Davis\n'
              'Asia - Bangkok/Barnaul/Ho_Chi_Minh/Jakarta/Novokuznetsk/Novosibirsk/Phnom_Penh/Pontianak/Tomsk/Vientiane\n'
              'Indian - Christmas'),
    ('+7:00/+8:00', 'Asia/Hovd/Krasnoyarsk'),
    ('+8:00', 'Asia/Brunei/Makassar'),
    ('+8:00/+9:00', 'Asia - Choibalsan/Hong_Kong/Irkutsk/Macau/Manila/Shanghai/Taipei/Ulaanbaatar\n'
                    'Australia - Perth'),
    ('+8:00/+7:20', 'Asia/Kuala_Lumpur/Singapore'),
    ('+8:00/+8:20', 'Asia/Kuching'),
    ('+8:45/+9:45', 'Australia/Eucla'),
    ('+9:00/+10:00', 'Asia/Chita/Seoul/Tokyo/Yakutsk'),
    ('+9:00', 'Asia - Dili/Jayapura/Pyongyang\n'
              'Pacific - Palau'),
    ('+9:00/+11:00', 'Asia/Khandyga'),
    ('+9:30/+10:30', 'Australia/Adelaide/Broken_Hill/Darwin'),
    ('+10:00', 'Antarctica - DumontDUrville\n'
               'Pacific - Chuuk/Port_Moresby'),
    ('+10:00/+11:00', 'Antarctica - Macquarie\n'
                      'Asia - Vladivostok\n'
                      'Australia - Brisbane/Currie/Hobart/Lindeman/Melbourne/Sydney\n'
                      'Pacific - Guam/Saipan'),
    ('+10:00/+12:00', 'Asia/Ust-Nera'),
    ('+10:30/+11:00', 'Australia/Lord_Howe'),
    ('+11:00', 'Antarctica - Casey\n'
               'Asia - Sakhalin\n'
               'Pacific - Bougainville/Guadalcanal/Kosrae/Pohnpei'),
    ('+11:00/+12:00', 'Asia - Magadan/Srednekolymsk\n'
                      'Pacific - Efate/Norfolk/Noumea'),
    ('+12:00/+13:00', 'Antarctica - McMurdo\n'
                      'Pacific - Auckland/Fiji'),
    ('+12:00', 'Asia - Anadyr/Kamchatka\n'
               'Pacific - Funafuti/Kwajalein/Majuro/Nauru/Tarawa/Wake/Wallis'),
    ('+12:45/+13:45', 'Pacific/Chatham'),
    ('+13:00/+14:00', 'Pacific/Apia/Tongatapu'),
    ('+13:00', 'Pacific/Enderbury/Fakaofo'),
    ('+14:00', 'Pacific/Kiritimati')
]
