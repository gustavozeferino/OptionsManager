import zipfile
from datetime import datetime
from decimal import Decimal
from dadosb3.models import CotacaoHistorica

def process_cothist_line(data):
    if len(data) < 245 or data[0:2] != '01':
        return None

    try:
        dtpreg_str = data[2:10]
        dtpreg = datetime.strptime(dtpreg_str, "%Y%m%d").date() if dtpreg_str.strip() else None
        
        datven_str = data[202:210]
        datven = datetime.strptime(datven_str, '%Y%m%d').date() if datven_str.strip() and datven_str != '99991231' else None

        preabe = Decimal(data[56:69]) / 100 if data[56:69].strip() else None
        premax = Decimal(data[69:82]) / 100 if data[69:82].strip() else None
        premin = Decimal(data[82:95]) / 100 if data[82:95].strip() else None
        premed = Decimal(data[95:108]) / 100 if data[95:108].strip() else None
        preult = Decimal(data[108:121]) / 100 if data[108:121].strip() else None
        preofc = Decimal(data[121:134]) / 100 if data[121:134].strip() else None
        preofv = Decimal(data[134:147]) / 100 if data[134:147].strip() else None
        preexe = Decimal(data[188:201]) / 100 if data[188:201].strip() else None
        voltot = Decimal(data[170:188]) / 100 if data[170:188].strip() else None

        totneg = int(data[147:152]) if data[147:152].strip() else None
        quatot = int(data[152:170]) if data[152:170].strip() else None

        return CotacaoHistorica(
            tipreg=data[0:2].strip(),
            dtpreg=dtpreg,
            codbdi=data[10:12].strip(),
            codneg=data[12:24].strip(),
            tpmerc=data[24:27].strip(),
            nomres=data[27:39].strip(),
            especi=data[39:49].strip(),
            prazot=data[49:52].strip(),
            modref=data[52:56].strip(),
            preabe=preabe,
            premax=premax,
            premin=premin,
            premed=premed,
            preult=preult,
            preofc=preofc,
            preofv=preofv,
            totneg=totneg,
            quatot=quatot,
            voltot=voltot,
            preexe=preexe,
            indopc=data[201:202].strip(),
            datven=datven,
            fatcot=data[210:217].strip(),
            ptoexe=data[217:230].strip(),
            codisi=data[230:242].strip(),
            dismes=data[242:245].strip()
        )
    except Exception as e:
        print(f"Error processing line: {e}")
        return None

def ingest_cothist_file(file_path, progress_callback=None):
    instances = []
    chunk_size = 5000

    def process_file_obj(f):
        count = 0
        for line in f:
            if isinstance(line, bytes):
                try:
                    line = line.decode('utf-8-sig')
                except UnicodeDecodeError:
                    line = line.decode('iso-8859-1')
            
            if len(line) < 245:
                continue

            obj = process_cothist_line(line)
            if obj:
                instances.append(obj)
                count += 1
                
            if len(instances) >= chunk_size:
                CotacaoHistorica.objects.bulk_create(instances, ignore_conflicts=True)
                instances.clear()
                if progress_callback:
                    progress_callback(count)

        if instances:
            CotacaoHistorica.objects.bulk_create(instances, ignore_conflicts=True)
            instances.clear()
            if progress_callback:
                progress_callback(count)
        
        return count


    if file_path.lower().endswith('.zip'):
        with zipfile.ZipFile(file_path, 'r') as z:
            for filename in z.namelist():
                if filename.lower().endswith('.txt'):
                    with z.open(filename) as f:
                        return process_file_obj(f)
    else:
        with open(file_path, 'rb') as f:
            return process_file_obj(f)
    return 0
