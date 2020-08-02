import keyring
from thehive4py.api import TheHiveApi
from thehive4py.models import CaseObservable, CustomField, Case, CustomFieldHelper, CaseTask
from os import sys, path
sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))
from helpers.qrhelper import qrhelper
from helpers.sqlhelper import sqlhelper
from helpers.loghelper import loghelper
logger = loghelper('qradar-thehive-sync')


# #Mandatory Settings ######################
qr_url='https://qradar'
qr_token = keyring.get_password('qr','can')
api_ver = "12.0"
thehive_url="https://thehive"
thehive_token = keyring.get_password('hive', 'can')
# Maximum count of offenses to query at a time. Just in case, if some QRadar rules goes wild.
max_count_offenses = 10
# Maximum count of properties to sync as observables,like IPs/Usernames. Just in case,a Ddos etc. may have too many.
max_event_count = 10
# Offense sync starts below this Offense ID >. You may want to keep some old offenses out of theHive.
offense_start_from = 6
# Test offense descriptions: put below text(s - list) in any part of your test offense name(case insensitive),those will be ignored.
test_offense_descs = ['Dummy']
# Put an offense note to the synced offenses, edit the note below.
offense_note = 'Offense synced to The Hive - Case ID:{}'
# Qradar  Offense Closing Text that you have - /siem/offense_closing_reasons
offense_closing_text= 'Non-Issue'
# Any Qradar property which you want to enrich as an observable, even if it is not part of the offense details/offense source.
# Use AQL field names only, you can find the names by looking from Log Activity > Advanced Search. Add with corresponding TheHive dataType.
qradar_observable_mapping = {"sourceip": "ip", "destinationip": "ip", "username": "other"}
# Custom fields to create on theHive, check theHive types.This is just for creating, you need to post the values within the code.
custom_fields = {
                "qradar_id":{"desc":"QRadar Offense ID", "type":"number"},
                "offense_source":{"desc":"QRadar Offense Source", "type":"string"},
                "qradar_username":{"desc":"QRadar Custom Username", "type":"string"}
                }
# #End of Settings #########################


# #Connect to Qradar
qr = qrhelper(qr_url, qr_token, api_ver)
logger.info('Connected to Qradar')

# #Connect to TheHive
try:
    hive_api = TheHiveApi(thehive_url, thehive_token, cert=False)
    logger.info('Connected to TheHive')
except Exception as e:
    logger.error('Error at connecting to TheHive:{} Error:{}'.format(thehive_url, e))
    sys.exit(1)

# #Connect to Sqlite DB and tables or create new.
sl = sqlhelper('qradar-sync.db')
case_table = 'cases'
enrichment_table = 'enrichments'
logger.info('Connected to Sqlite DB')
sl.create_table(case_table, 'id INTEGER PRIMARY KEY, case_id TEXT, status TEXT')
sl.create_table(enrichment_table, 'id INTEGER, enrichment_id TEXT, enrichment_type TEXT, status TEXT')
sl.create_index('idx_case_id','cases','case_id')
sl.create_index('idx_id_enrichment_id_status', 'enrichments', 'id, enrichment_id, status')

# #Create custom_fields in TheHive(like Qradar_Id) if it's not there.
for k,v in custom_fields.items():
    CustomField.name = k
    CustomField.reference = k
    for key, val in v.items():
        if key == 'desc':
            CustomField.description = val
        elif key == 'type':
            CustomField.type = val
            field_type = val
    CustomField.options = ''
    CustomField.madatory = False ##TODO: Check on TheHive4Py issues for this typo -madatory- to be fixed
    if hive_api._check_if_custom_field_exists(CustomField) == False:
        logger.info('New custom_field created:{}'.format(k))
        hive_api.create_custom_field(CustomField)

# #Check offense desc and filter out test offenses
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
            logger.error('Error at observable creation.Case Id::{} - Err:[]'.format(case_id, err))

# #Template AQL for enrichments
def aql_enrich_qry(field, offense_id):
    aql_qry = "SELECT \"{}\" FROM events WHERE inOffense({}) GROUP BY \"{}\" LIMIT {} START '{}' STOP '{}'"\
            .format(field, offense_id, field, max_event_count, offense_start_time, offense_lastupdate_time)
    return aql_qry

# # A dummy sev,tlp assignment for initial case creation - using ONLY offense magnitude.
# severity: (0: not set; 1: low; 2: medium; 3: high) TLP: (-1: unknown; 0: white; 1: green; 2: amber; 3: red)
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

#Check for closed cases from DB before resync.
get_cases = sl.get_records_by_val(case_table, 'case_id', 'status', 'Open')
for i in get_cases:
    if hive_api.get_case(i[0]).json()['status'] == 'Resolved':
        for i in sl.get_records_by_val(case_table, 'id', 'case_id', i[0]):
            if qr.get_offense_details(i[0])['status'] == 'OPEN':
                if qr.close_offense(i[0], offense_closing_text) == True:
                    sl.update_record(case_table, 'status', 'Closed', 'id', i[0])
                    sl.update_record(enrichment_table, 'status', 'Closed', 'id', i[0])

#Process new offenses
qr_resp = qr.get_offenses(open=True, max_items=max_event_count)
new_offense_list = []
if qr_resp is not None:
    for i in qr_resp:
        # Check offense_start_from ID-number and process only bigger
        if i['id'] > offense_start_from:
            # Check offense description(name) for test, dummy offenses
            if check_test_offenses(i['description'].strip()) == False:
                # Check sqlite db for past synced offenses
                if sl.check_record(case_table, 'id', i['id']) is not True:
                    # New offenses to process
                    new_offense_list.append(i['id'])
if len(new_offense_list) == 0 :
    logger.info('No new offense to sync right now. All good!')

# # Reconn and check-create new cases
qr = qrhelper(qr_url, qr_token, api_ver)
for i in new_offense_list:
    print('-------Processing new offense-------:', i)
    # # Getting values
    offense_details = qr.get_offense_details(i)
    offense_id = offense_details['id']
    offense_desc = offense_details['description'].strip().replace('\n','')
    offense_type_name = qr.get_offense_type_name(offense_details['offense_type'])
    offense_type_property = qr.get_offense_type_property(offense_details['offense_type'])
    offense_src_nw = offense_details['source_network']
    offense_dst_nw = offense_details['destination_networks'][0]
    offense_magnitude = offense_details['magnitude']
    offense_start_time = offense_details['start_time']
    offense_lastupdate_time = offense_details['last_updated_time']
    if offense_lastupdate_time == offense_start_time:
        offense_lastupdate_time = offense_lastupdate_time + 1
    offense_source = offense_details['offense_source']
    offense_link = qr_url + '/console/qradar/jsp/QRadar.jsp?appName=Sem&pageId=OffenseSummary&summaryId={}'.format(offense_id)
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
            sl.insert_record(enrichment_table, 'id, enrichment_id, enrichment_type, status', '"{}","{}","{}","{}"'.format(offense_id, aql_id, 'destinationip', 'Open'))
            #sl.new_enrichment_record(offense_id, aql_id, 'destinationip', 'Open')
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
            sl.insert_record(enrichment_table, 'id, enrichment_id, enrichment_type, status', '"{}","{}","{}","{}"'.format(offense_id, aql_id, 'username', 'Open'))
            records = qr.get_aql_results(aql_id)
            if records:
                retval = parse_get_aql(records, 'username')
                if retval:
                    for item in retval:
                        if item != None:
                            username_list.append(item)
                            sl.update_record(enrichment_table, 'status', 'Closed', 'enrichment_id', aql_id)

    # # Adding custom_fields values to the case - static mapping.
    custom_fields = CustomFieldHelper()
    custom_fields.add_number('qradar_id', offense_id)
    custom_fields.add_string('offense_source', offense_source)
    custom_fields.build()

    tlp = offense_severity_mapper(offense_magnitude)['sev']

    # #Case - Offense summary md.
    build_desc = """|Offense Summary:|\n|---|\n|Offense Description: {}|\n|Source NW: {}|\n|Destination NW: {}|\n|Source IPs: {}|\n|Local Destination IPs: {}|\n|Remote Destination IPs: {}|\n|Usernames: {}|\n---\nLink to the Offense: {}""".format(offense_desc, offense_src_nw, offense_dst_nw, source_address_list,
                                                       local_dest_list, remote_dest_list, username_list, offense_link)

    # #Some sample tasks-response actions for posting in the case. Customize per your reqs.
    # #TODO: You can also utilize - thehive-playbook-creator - for dynamic task/playbook assignment using your QRadar rule groups. 
    tasks = [CaseTask(title='PB:- Phase:Identification'), CaseTask(title='PB: - Phase:Remediation'), CaseTask(title='PB: - Phase:Lessons Learned', status='Waiting', flag=True)]

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
            sl.insert_record(case_table, 'id, case_id, status', '"{}","{}","{}"'.format(offense_id, case_id, 'Open'))
            #sl.new_case_record(offense_id, case_id, 'Open')
            logger.info('Case created. Case Id:{} - Case Num:{}'.format(case_id,case_num))
    except Exception as err:
        logger.error('Error at case creation.:{}'.format(err))
        sys.exit(1)

    if case_id:
        print('-------Posting Observables--------')
        if offense_source not in list(observables_dict.values()):
            # Offense source type and val for observables
            off_source_mapping = offense_observable_mapping(offense_type_property, offense_source)
            if off_source_mapping: # {'ip': '8.8.8.8'}
                obs_id = create_observables(off_source_mapping, case_id)
                logger.info('Observable created. Case Id:{} - Obsv.Id:{}'.format(case_id, obs_id))

        # Post-Get custom property based obs which we defined in qradar_observable_mapping dict.
        for k, v in qradar_observable_mapping.items():
            if k.lower() != offense_type_property.lower(): ##Offense source already added
                aql_id = qr.post_aql(aql_enrich_qry(k,offense_id))
                if aql_id:
                    sl.insert_record(enrichment_table, 'id, enrichment_id, enrichment_type, status', '"{}","{}","{}","{}"'.format(offense_id, aql_id, k, 'Open'))
                    records = qr.get_aql_results(aql_id)
                    if records:
                        retval = parse_get_aql(records, k)
                        if retval:
                            for item in retval:
                                if item != None:
                                    custom_prop_mapping = offense_observable_mapping(k, item)
                                    obs_id = create_observables(custom_prop_mapping, case_id)
                                    sl.update_record(enrichment_table, 'status', 'Closed', 'enrichment_id', aql_id)
                                    logger.info('Observable created. Case Id:{} - Obsv.Id:{}'.format(case_id,obs_id))

# #Check for unfinished AQL queries from Sqlite for previous case enrichments.
# #Close the enrichment records after update or result set==None, which means property does not in relation with the offense.
chk_aql_dict = {}
open_enrichments = sl.run_qry("SELECT c.case_id, e.enrichment_id from cases c LEFT OUTER JOIN enrichments e ON c.id = e.id where e.status = 'Open'")
if len(open_enrichments) > 0:
    print('-------Checking for past enrichment results--------')
    for i in open_enrichments:
        chk_aql_dict[i[0]] = i[1]
        for k,v  in chk_aql_dict.items():
            records = qr.get_aql_results(v)
            if records:
                obs_type = sl.get_records_by_val(enrichment_table, 'enrichment_type', 'enrichment_id', v)[0][0]
                print(obs_type)
                retval = parse_get_aql(records, obs_type)
                if retval:
                    for item in retval:
                        if item != None:
                            custom_prop_mapping = offense_observable_mapping(obs_type, item[0])
                            obs_id = create_observables(custom_prop_mapping, k)
                sl.update_record(enrichment_table, 'status', 'Closed', 'enrichment_id', v)
                logger.info('Past enrichment checks finished.')
else :
    logger.info('No new enrichment to check right now. All good!')