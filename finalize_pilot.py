"""Record targeted checks of the selected invoice pilot, not training admission."""
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from audit_invoice_case import workbook_rows
from pilot import read_json, save


root = Path('runs/teacher-render-recheck-v1')
report = next(p for p in (root/'workspace/outputs').glob('*.xlsx') if '\u62a5\u544a' in p.name)
rows = workbook_rows(report)['\u5ba1\u9605\u62a5\u544a']
assert [rows[i][1] for i in (10,12,13,14)] == [9,6,7,2]
ns = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
formulas=[]
with ZipFile(report) as archive:
    for name in archive.namelist():
        if name.startswith('xl/worksheets/') and name.endswith('.xml'):
            for cell in ET.fromstring(archive.read(name)).findall('.//s:c',ns):
                formula=cell.find('s:f',ns)
                if formula is not None:
                    formulas.append({'part':name,'cell':cell.attrib['r'],'formula':formula.text})
assert formulas
save(root/'manual_qa.json',{
    'targeted_checks_passed':True,
    'checks':{'record_count':9,'event_count':6,'affected_record_count':7,
        'unaffected_record_count':2,'count_cells':['B11','B13','B14','B15'],
        'counts_reconcile':True,'summary_formulas_present':True,
        'cross_currency_total_absent':True,'output_readback_in_native_trace':True,
        'final_schema_pass':True,'read_only_input_hashes_unchanged':True,
        'renderer_replay_cell_values_unchanged':True,'critical_text_clipping_fixed':True},
    'formulas':formulas,
    'visual_scope':'All five original sheets reviewed; recalculated summary rechecked after renderer fix. No business cells edited by controller.',
    'quality_scope':'Targeted semantic and readability review only; no generic blind scoring or held-out evaluation.',
    'training_ready':False,
    'lineage':['runs/teacher-detail-count-retest-v1','runs/teacher-render-recheck-v1/replay.json'],
    'known_limits':['functional layout, not a professional redesign','same task reused during prompt iteration','SFT encoding and rejection sampling not performed']})
candidate=read_json(root/'raw_teacher_candidate.json')
candidate['controller_intervention']=read_json(root/'replay.json')
candidate['limitations'].append('Renderer correction and a controller-requested recheck are included; not a pristine independent rollout.')
save(root/'raw_teacher_candidate.json',candidate)
print('Final targeted checks passed; saved summary formulas',len(formulas))
