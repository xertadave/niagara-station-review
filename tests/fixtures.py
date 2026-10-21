"""A made-up station backup for the tests.  Every name in it is invented.

It contains one of each thing the checks look for: a manual override, a failed sensor, a CO2
point labelled as humidity, a device named against the convention, a missing point, a disabled
point, inconsistent fallbacks, an empty schedule, an alarm route to a disabled station, user
account issues, an old backup, duplicate M-Bus addresses and a low frost setpoint.
"""
import io
import zipfile

H = [0]


def h():
    H[0] += 1
    return format(H[0], 'x')


def link(src_h, sslot, tslot, name='Link'):
    return (f'<p n="{name}" t="b:Link"><p n="sourceOrd" v="h:{src_h}"/><p n="relationTags" v=""/><p n="relationId" v="n:dataLink"/>'
            f'<p n="sourceSlotName" v="{sslot}"/><p n="targetSlotName" v="{tslot}"/></p>')


def sv(name, value, status=None, flags=''):
    st = f'<p n="status" v="{status}"/>' if status is not None else ''
    f = f' f="{flags}"' if flags else ''
    return f'<p n="{name}"{f} t="b:StatusNumeric"><p n="value" v="{value}"/>{st}</p>'


def sb(name, value, status=None):
    st = f'<p n="status" v="{status}"/>' if status is not None else ''
    return f'<p n="{name}" t="b:StatusBoolean"><p n="value" v="{value}"/>{st}</p>'


FAC_C = 'units=u:celsius;&#xb0;C;(K);+273.15;|precision=i:1'
FAC_PPM = 'units=u:parts per million;ppm;;*1.0E-6;|precision=i:0'
FAC_PCT = 'units=u:percent;%;;;|precision=i:0'
FAC_KWH = 'units=u:kilowatt hour;kWh;;;|precision=i:0'


def bac_point(name, typ, obj, facets='', extra='', enabled=True, hh=None):
    hh = hh or h()
    en = '' if enabled else '<p n="enabled" v="false"/>'
    fac = f'<p n="facets" t="b:Facets" v="{facets}"/>' if facets else ''
    return hh, (f'<p n="{name}" h="{hh}" t="c:{typ}">{fac}<p n="proxyExt" h="{h()}" t="bac:BacnetNumericProxyExt">{en}'
                f'<p n="objectId" t="bac:BacnetObjectIdentifier" v="{obj}"/></p>{extra}</p>')


def bac_device(name, model, inst, points_xml, vendor='Example Controls Ltd', sw='App 1.0'):
    return (f'<p n="{name}" h="{h()}" t="bac:BacnetDevice"><p n="points" h="{h()}" t="bac:BacnetPointDeviceExt">{points_xml}</p>'
            f'<p n="config" h="{h()}" t="bac:BacnetConfigDeviceExt"><p n="deviceObject" h="{h()}" t="bac:BacnetDeviceObject">'
            f'<p n="objectId" t="bac:BacnetObjectIdentifier" v="device:{inst}"/><p n="objectName" v="{name}"/>'
            f'<p n="vendorName" v="{vendor}"/><p n="modelName" v="{model}"/><p n="firmwareRevision" v="2.0 SN &#x0;"/>'
            f'<p n="applicationSoftwareVersion" v="{sw}"/></p></p></p>')


def build_xml():
    H[0] = 0
    # ---- terminal units: VAV-1-01..04 follow the convention, VAV-9 does not
    vavs = []
    fallbacks = ['21.0', '21.0', '21.0', '24.0', '30.0']
    for i, name in enumerate(['VAV-1-01', 'VAV-1-02', 'VAV-1-03', 'VAV-1-04', 'VAV-9']):
        pts = bac_point('Room Temp', 'NumericPoint', 'analogInput:1', FAC_C)[1]
        pts += bac_point('Setpoint', 'NumericWritable', 'analogValue:1', FAC_C, sv('fallback', fallbacks[i]))[1]
        if name != 'VAV-1-03':                                   # missing point on one unit
            pts += bac_point('Damper', 'NumericWritable', 'analogOutput:1', FAC_PCT, enabled=(name != 'VAV-1-02'))[1]
        if name == 'VAV-1-04':                                   # manual emergency override
            pts += bac_point('Mode', 'BooleanWritable', 'binaryValue:1', '', sb('in1', 'true') + sb('in8', 'false'))[1]
        else:
            pts += bac_point('Mode', 'BooleanWritable', 'binaryValue:1', '')[1]
        vavs.append(bac_device(name, 'TU100', 100 + i, pts))

    # ---- I/O module with a failed sensor and a CO2 sensor named as humidity
    ui1_h, ui1 = bac_point('Temperature_UI1', 'NumericPoint', 'analogInput:0', FAC_C)
    ui8_h, ui8 = bac_point('Voltage_UI8', 'NumericPoint', 'analogInput:7', FAC_PPM)
    ui5_h, ui5 = bac_point('Temperature_UI5', 'NumericPoint', 'analogInput:4', FAC_PCT)
    kwh_h, kwh = bac_point('Total Energy', 'NumericPoint', 'analogInput:9', FAC_KWH)
    io = bac_device('IOMOD', 'IO-38', 900, ui1 + ui8 + ui5 + kwh, vendor='IO Maker')

    room_h, hum_h, sup_h, frost_h, tstat_h = h(), h(), h(), h(), h()
    wires = (f'<p n="WireSheets" h="{h()}" t="b:Folder">'
             f'<p n="RoomTemp" h="{room_h}" t="c:NumericWritable"><p n="facets" t="b:Facets" v="{FAC_C}"/><p n="in10" f="tsL"/>{link(ui1_h, "out", "in10")}</p>'
             f'<p n="ExtractHum" h="{hum_h}" t="c:NumericWritable"><p n="facets" t="b:Facets" v="{FAC_PPM}"/><p n="in10" f="tsL"/>{link(ui8_h, "out", "in10")}</p>'
             f'<p n="Supply" h="{sup_h}" t="c:NumericWritable"><p n="facets" t="b:Facets" v="{FAC_C}"/><p n="in10" f="tsL"/>{link(ui5_h, "out", "in10")}</p>'
             f'<p n="FrostSP" h="{frost_h}" t="c:NumericWritable"><p n="facets" t="b:Facets" v="{FAC_C}"/>{sv("fallback", "2.0")}</p>'
             f'<p n="Tstat" h="{tstat_h}" t="kitControl:Tstat">{sv("cv", "-3276.800048828125", flags="sL")}{link(room_h, "out", "cv")}</p>'
             f'<p n="CO2Reset" h="{h()}" t="kitControl:Reset">{sv("inA", "455.0", flags="sL")}{link(hum_h, "out", "inA")}</p>'
             f'<p n="SupLoop" h="{h()}" t="kitControl:LoopPoint">{sv("controlledVariable", "19.5", flags="sL")}{link(sup_h, "out", "controlledVariable")}</p>'
             f'<p n="EnergyCopy" h="{h()}" t="kitControl:Add">{sv("inA", "123456.0", flags="sL")}{link(kwh_h, "out", "inA")}</p>'
             f'<p n="Enrol" h="{h()}" t="c:BooleanWritable">{sb("in8", "true")}</p>'
             f'<p n="Note" h="{h()}" t="b:WsTextBlock"><p n="text" v="Example note"/></p>'
             f'</p>')

    sched = (f'<p n="EmptySched" h="{h()}" t="sch:BooleanSchedule"><p n="schedule" h="{h()}" t="sch:CompositeSchedule">'
             f'<p n="specialEvents" h="{h()}" t="sch:CompositeSchedule"></p></p>'
             f'<p n="ext" h="{h()}" t="nd:NiagaraScheduleImportExt"/></p>'
             f'<p n="Occupancy" h="{h()}" t="sch:BooleanSchedule"><p n="schedule" h="{h()}" t="sch:CompositeSchedule">'
             f'<p n="week" h="{h()}" t="sch:WeekSchedule"><p n="monday" h="{h()}" t="sch:DailySchedule"><p n="day" h="{h()}" t="sch:DaySchedule">'
             f'<p n="time" h="{h()}" t="sch:TimeSchedule"><p n="start" t="b:Time" v="07:00:00.000"/><p n="finish" t="b:Time" v="18:00:00.000"/>'
             f'<p n="effectiveValue" t="b:StatusBoolean"><p n="value" v="true"/></p></p></p></p></p></p></p>')

    niagara = (f'<p n="NiagaraNetwork" h="{h()}" t="nd:NiagaraNetwork">'
               f'<p n="SUPERVISOR" h="{h()}" t="nd:NiagaraStation"><p n="address" t="b:Ord" v="ip:10.0.0.10"/><p n="version" v="4.15.5.22"/>'
               f'<p n="clientConnection" h="{h()}" t="f:FoxClientConnection"><p n="useFoxs" t="b:Boolean" v="true"/>'
               f'<p n="lastConnectTime" t="b:AbsTime" v="2026-10-01T08:00:00.000+01:00"/></p>'
               f'<p n="schedules" h="{h()}" t="nd:NiagaraScheduleDeviceExt">{sched}</p></p>'
               f'<p n="OLDSTATION" h="{h()}" t="nd:NiagaraStation"><p n="address" t="b:Ord" v="ip:OLD-PC"/><p n="enabled" v="false"/></p></p>')

    mbus = (f'<p n="MbusEnergy" h="{h()}" t="mbus:MbusNetwork">'
            f'<p n="HEAT1" h="{h()}" t="mbus:MbusDevice"><p n="primaryAddress" v="1"/><p n="secondaryAddress" v="1111222233334444"/></p>'
            f'<p n="HEAT2" h="{h()}" t="mbus:MbusDevice"><p n="primaryAddress" v="2"/><p n="secondaryAddress" v="1111222233334444"/></p></p>')

    bacnet = (f'<p n="BacnetNetwork" h="{h()}" t="bac:BacnetNetwork"><p n="localDevice" h="{h()}" t="bac:LocalBacnetDevice">'
              f'<p n="objectId" t="bac:BacnetObjectIdentifier" v="device:5"/><p n="firmwareRevision" v="4.15.1.16"/></p>'
              f'<p n="VAV" h="{h()}" t="bac:BacnetDeviceFolder">{"".join(vavs)}</p>{io}</p>')

    users = (f'<p n="UserService" h="{h()}" t="b:UserService">'
             f'<p n="admin" h="{h()}" t="b:User"><p n="roles" v="admin"/></p>'
             f'<p n="old.contractor" h="{h()}" t="b:User"><p n="roles" v="admin"/><p n="authenticator" h="{h()}" t="b:PasswordAuthenticator">'
             f'<p n="passwordConfig" h="{h()}" t="b:UserPasswordConfiguration"><p n="lastPasswordChange" t="b:AbsTime" v="2020-01-01T09:00:00.000Z"/></p></p></p>'
             f'<p n="temp.user" h="{h()}" t="b:User"><p n="expiration" v="2024-01-01T23:59:00.000Z"/><p n="roles" v="engineer"/></p>'
             f'<p n="new.user" h="{h()}" t="b:User"><p n="roles" v="admin"/><p n="authenticator" h="{h()}" t="b:PasswordAuthenticator">'
             f'<p n="passwordConfig" h="{h()}" t="b:UserPasswordConfiguration"><p n="forceResetAtNextLogin" v="true"/></p></p></p>'
             f'<p n="PANEL" h="{h()}" t="b:User"><p n="roles" v="admin"/></p></p>')

    services = (f'<p n="Services" h="{h()}" t="b:ServiceContainer">'
                f'<p n="AlarmService" h="{h()}" t="a:AlarmService"><p n="General" h="{h()}" t="a:AlarmClass"/>'
                f'<p n="ToOld" h="{h()}" t="a:StationRecipient"><p n="remoteStation" v="OLDSTATION"/></p>'
                f'<p n="ToSup" h="{h()}" t="a:StationRecipient"><p n="remoteStation" v="SUPERVISOR"/></p></p>'
                f'<p n="BackupService" h="{h()}" t="bk:BackupService"><p n="BackupRecord1" f="h" t="bk:BackupRecord">'
                f'<p n="timestamp" t="b:AbsTime" v="2024-03-01T10:00:00.000Z"/><p n="host" v="10.0.0.10"/><p n="user" v="admin"/></p></p>'
                f'{users}<p n="FoxService" h="{h()}" t="f:FoxService"><p n="foxsEnabled" v="true"/></p>'
                f'<p n="WebService" h="{h()}" t="w:WebService"><p n="httpsEnabled" v="true"/></p></p>')

    hist = f'<p n="H" h="{h()}" t="h:NumericIntervalHistoryExt"/>'
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<bajaObjectGraph version="4.0">'
           f'<p m="b=baja" t="b:UnrestrictedFolder"><p n="station" h="{h()}" t="b:Station"><p n="stationName" v="PLANT01"/>'
           f'{services}<p n="Drivers" h="{h()}" t="d:DriverContainer">{niagara}{bacnet}{mbus}{wires}</p>{hist}</p></p></bajaObjectGraph>')
    return xml


def build_bog():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(zipfile.ZipInfo('file.xml', (2026, 10, 1, 9, 30, 0)), build_xml())
    return buf.getvalue()
