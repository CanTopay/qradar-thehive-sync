import keyring
from os import sys, path
sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))
from helpers.sqlhelper import sqlhelper
from helpers.qrhelper import qrhelper
from thehive4py.api import TheHiveApi
from thehive4py.models import Case, CustomFieldHelper, CaseTask, CaseObservable
import logging

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Enable logging
from lib.loghelper import loghelper
logger = loghelper('qradar-thehive-sync')

# #Settings for IBM QRadar
qr_url="https:/.com/"
qr_token = keyring.get_password('qr','can')
api_ver = "12.0"

# #Settings for TheHive
thehive_url="https://.com:9000"
thehive_token = keyring.get_password('hive','can')

# # Check offense desc and filter out test offenses using prefix Dummy --xxx--.
def check_test_offenses(offense_desc):
    test_offense = False
    for i in test_offense_descs:
        if i.lower() in offense_desc.lower()[:len(i)]:
            test_offense = True
    return test_offense

# #Check offense fields which we defined in settings.py to map observable types
def offense_observable_mapping(obs_type, obs_src):
    obs_dict = {}
    for k,v in qradar_observable_mapping.items():
        if obs_type.lower() == k.lower():
            obs_dict[v] = obs_src
    return obs_dict

# #AQL results parsing
def parse_get_aql(get_aql_results, target_item):
    values_list = []
    for i in get_aql_results['events']:
        for k,v in i.items():
            if k == target_item:
                if v != None:
                    values_list.append(v)
    return values_list

# #Create observables
def create_observables(items_dict, case_id):
    for k, v in items_dict.items():
        observable = CaseObservable(dataType=k, data=[v], ioc=True, )
        try:
            resp = hive_api.create_case_observable(case_id, observable)
            if resp.status_code == 201:
                id = resp.json()['id']
                return id
        except Exception as err:
            lgr.error('Error at observable creation.Case Id::{} - Err:[]'.format(case_id, err))
            sys.exit(1)

# #Prepare AQL query for enrichments
def aql_enrich_qry(field, offense_id):
    aql_qry = "SELECT \"{}\" FROM events WHERE inOffense({}) GROUP BY \"{}\" LIMIT {} START '{}' STOP '{}'"\
            .format(field, offense_id, field, max_event_count, offense_start_time, offense_lastupdate_time)
    return aql_qry

# # A dummy sev,tlp assignment for initial case creation - using ONLY offense magnitude.
# severity: (0: not set; 1: low; 2: medium; 3: high)
# TLP: (-1: unknown; 0: white; 1: green; 2: amber; 3: red)
#TODO: Triage-assignment severity calculation.
def offense_severity_mapper(magnitude):
    mapper = {}
    sev = 0
    tlp = 0
    if magnitude <= 2:
        sev = 1
        tlp = 0
    elif magnitude >= 3 and magnitude <= 6:
        sev = 2
        tlp = 1
    elif magnitude >= 7 and magnitude < 9:
        sev = 3
        tlp = 2
    elif magnitude > 9:
        sev = 3
        tlp = 3
    mapper['sev'] = sev
    mapper['tlp'] = tlp
    return mapper

# # Connect to DB, or create a new one.
lgr.info('Connecting to Sqlite DB:{} in {}'.format(case_db, db_path))
sl = sqlite_helper()
sl.create_case_table()
sl.create_enrichment_table()

# #Connect to TheHive
try:
    hive_api = TheHiveApi(thehive_url, thehive_token, cert=False)
    lgr.info('Connected to TheHive:{}'.format(thehive_url))
except Exception as e:
    lgr.error('Error at connecting to TheHive:{} Error:{}'.format(thehive_url, e))
    sys.exit(1)

# # Query Qradar for open Offenses
lgr.info('Connecting to Qradar:{}'.format(qr_url))
qr = qradar()
# #Check for already closed cases
get_cases = sl.get_records_by_field(case_table, 'case_id', 'status', 'Open')
for i in get_cases:
    #print(hive_api.get_case('qt-0wHABMIVxRx-xHkPO').json())
    if hive_api.get_case(i[0]).json()['status'] == 'Resolved':
        for i in sl.get_records_by_field(case_table, 'id', 'case_id', i[0]):
            if qr.get_offense_details(i[0])['status'] == 'OPEN':
                qr.close_offense(i[0], offense_closing_reason_id)
                sl.update_record(case_table, 'status', 'Resolved', 'id', i[0])
                sl.update_record(enrichment_table, 'status', 'Closed', 'id', i[0])

# #Process new offenses
qr_resp = qr.get_offenses(open=True, max_items=max_event_count)
new_offense_list = []
if qr_resp is not None:
    for i in qr_resp:
        # Check offense_start_from ID-number and process only bigger
        if i['id'] > offense_start_from:
            # Check offense description(name) for test, dummy offenses
            if check_test_offenses(i['description'].strip()) == False:
                # Check sqlite db for past synced offenses
                if sl.check_synced(case_table, 'id', i['id']) is not True:
                    # New offenses to process
                    new_offense_list.append(i['id'])
if len(new_offense_list) == 0 :
    lgr.info('No new offense to sync right now. All good!')

# #Create new cases from offenses
qr = qradar()
for i in new_offense_list:
    print('-------Processing new offense-------:', i)
    # # Getting values
    offense_details = qr.get_offense_details(i)
    offense_id = offense_details['id']
    offense_desc = offense_details['description'].strip().replace('\n','')
    offense_type_name = qr.check_offense_type_name_in_offense(offense_details['offense_type'])
    offense_type_property = qr.check_offense_type_property_in_offense(offense_details['offense_type'])
    offense_src_nw = offense_details['source_network']
    offense_dst_nw = offense_details['destination_networks'][0]
    offense_magnitude = offense_details['magnitude']
    offense_start_time = offense_details['start_time']
    offense_lastupdate_time = offense_details['last_updated_time']
    offense_source = offense_details['offense_source']
    offense_link = qr_url + 'console/qradar/jsp/QRadar.jsp?appName=Sem&pageId=OffenseSummary&summaryId={}'.format(offense_id)
    #offense_rules = offense_details['rules']

    # #Getting some more static offense data to be enriched
    source_count = offense_details['source_count']
    source_address_ids = offense_details['source_address_ids']
    local_destination_count = offense_details['local_destination_count']
    local_destination_addresses_ids = offense_details['local_destination_address_ids']
    remote_destination_count = offense_details['remote_destination_count']
    username_count = offense_details['username_count']

    observables_dict = {}
    # #SIP list from static Offense data
    source_address_list = []
    if source_count >= 1:
        for index, x in zip(range(max_event_count), source_address_ids):
            if x is not None:
                sip = qr.get_source_addresses(x)
                observables_dict['ip'] = sip
                source_address_list.append(sip)

    # #Local DIP list from static Offense data
    local_dest_list = []
    if local_destination_count >= 1:
        for index, x in zip(range(max_event_count), local_destination_addresses_ids):
            if x is not None:
                dip = qr.get_local_destination_addresses(x)
                observables_dict['ip'] = dip
                local_dest_list.append(dip)

    # #Remote DIP list from static Offense data
    remote_dest_list = []
    if remote_destination_count >= 1:
        aql_id = qr.post_aql(aql_enrich_qry('destinationip', offense_id))
        if aql_id:
            sl.new_enrichment_record(offense_id, aql_id, 'destinationip', 'Open')
            records = qr.get_aql_results(aql_id)
            if records:
                retval = parse_get_aql(records, 'destinationip')
                if retval:
                    for item in retval:
                        if item != None:
                            observables_dict['ip'] = item
                            remote_dest_list.append(item)
                            sl.update_record(enrichment_table, 'status', 'Closed', 'enrichment_id', aql_id)

    # #Username list from static Offense data - don't post this as an observable
    username_list = []
    if username_count >= 1:
        aql_id = qr.post_aql(aql_enrich_qry('username', offense_id))
        if aql_id:
            sl.new_enrichment_record(offense_id, aql_id, 'username', 'Open')
            records = qr.get_aql_results(aql_id)
            if records:
                retval = parse_get_aql(records, 'username')
                print('retval', retval)
                if retval:
                    for item in retval:
                        if item != None:
                            username_list.append(item)
                            sl.update_record(enrichment_table, 'status', 'Closed', 'enrichment_id', aql_id)

    # #More static fields to create case - ALL FIELDS MUST BE CREATED ON THE HIVE with SAME REFERENCE NAME.
    custom_fields = CustomFieldHelper()
    custom_fields.add_number('offense_id', offense_id)
    custom_fields.add_string('offenseType', offense_type_name)
    custom_fields.add_string('offense_source', offense_source)
    custom_fields.add_number('offenseMagnitude',offense_magnitude)
    custom_fields.add_date('offenseStartTime',offense_start_time)
    custom_fields.add_date('offenseLastUpdate',offense_lastupdate_time)
    custom_fields.build()
    tlp = offense_severity_mapper(offense_magnitude)['sev']

    # #Markdown offense summary
    build_desc = """|Offense Summary:|\n|---|\n|Offense Description: {}|\n|Source NW: {}|\n|Destination NW: {}|\n|Source IPs: {}|\n|Local Destination IPs: {}|\n|Remote Destination IPs: {}|\n|Usernames: {}|\n---\nLink to the Offense: {}""".format(offense_desc, offense_src_nw, offense_dst_nw, source_address_list,
                                                       local_dest_list, remote_dest_list, username_list, offense_link)

    # #Some sample tasks-response actions for posting in the case. Customize per your reqs.
    # #TODO: Dynamic task-playbook assignment
    tasks = [CaseTask(title='PB:Malware response - Phase:Identification'), CaseTask(title='PB:Malware response - Phase:Remediation'), CaseTask(title='PB:Malware response - Phase:Lessons Learned', status='Waiting', flag=True)]

    #Build TheHive Case with custom fields
    thehive_case = Case(title=offense_desc,
                        tlp=tlp,
                        flag=True,
                        tags=['offense', 'qradar', offense_type_name],
                        description=build_desc,
                        customFields=custom_fields.fields,
                        tasks=tasks)

    print('-------Posting Case with initial values--------')
    case_id = None
    try:
        resp = hive_api.create_case(thehive_case)
        if resp.status_code == 201:
            case_id = resp.json()['id']
            case_num = resp.json()['caseId']
            qr.post_offense_note(offense_id, offense_note.format(case_num))
            sl.new_case_record(offense_id, case_id, 'Open')
            lgr.info('Case created. Case Id:{} - Case Num:{}'.format(case_id,case_num))
    except Exception as err:
        lgr.error('Error at case creation.:{}'.format(err))
        sys.exit(1)

    if case_id:
        print('-------Posting Observables--------')
        if offense_source not in list(observables_dict.values()):
            # Offense source type and val for observables
            off_source_mapping = offense_observable_mapping(offense_type_property, offense_source)
            if off_source_mapping: # {'ip': '8.8.8.8'}
                obs_id = create_observables(off_source_mapping, case_id)
                lgr.info('Observable created. Case Id:{} - Obsv.Id:{}'.format(case_id, obs_id))
        # Post-Get custom property based obs which we defined in qradar_observable_mapping dict.
        for k, v in qradar_observable_mapping.items():
            if k.lower() != offense_type_property.lower(): ##Offense source already added
                aql_id = qr.post_aql(aql_enrich_qry(k,offense_id))
                if aql_id:
                    sl.new_enrichment_record(offense_id, aql_id, k, 'Open')
                    records = qr.get_aql_results(aql_id)
                    if records:
                        retval = parse_get_aql(records, k)
                        if retval:
                            for item in retval:
                                if item != None:
                                    custom_prop_mapping = offense_observable_mapping(k, item)
                                    obs_id = create_observables(custom_prop_mapping, case_id)
                                    sl.update_record(enrichment_table, 'status', 'Closed', 'enrichment_id', aql_id)
                                    lgr.info('Observable created. Case Id:{} - Obsv.Id:{}'.format(case_id,obs_id))

# #Check for unfinished AQL queries from Sqlite for previous case enrichments.
# #Close the enrichment records after update or result set==None, which means property does not in relation with the offense.
chk_aql_dict = {}
open_enrichments = sl.run_sql("SELECT c.case_id, e.enrichment_id from cases c LEFT OUTER JOIN enrichments e ON c.id = e.id where e.status = 'Open'")
if len(open_enrichments) > 0:
    print('-------Checking for past enrichment results--------')
    for i in open_enrichments:
        chk_aql_dict[i[0]] = i[1]
        for k,v  in chk_aql_dict.items():
            records = qr.get_aql_results(v)
            if records:
                obs_type = sl.get_records_by_field(enrichment_table, 'enrichment_type', 'enrichment_id', v)[0][0]
                retval = parse_get_aql(records, obs_type)
                if retval:
                    for item in retval:
                        if item != None:
                            custom_prop_mapping = offense_observable_mapping(obs_type, item[0])
                            obs_id = create_observables(custom_prop_mapping, k)
                sl.update_record(enrichment_table, 'status', 'Closed', 'enrichment_id', v)
                lgr.info('Past enrichment checks finished.')
else :
    lgr.info('No new enrichment to check right now. All good!')