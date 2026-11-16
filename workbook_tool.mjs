import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile, FileBlob } from '@oai/artifact-tool';

// Trusted broker implementation. Model input is data, never JavaScript.
const spec = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
const scratch = path.dirname(process.argv[2]);
let wb;
if (spec.operation === 'create' || spec.operation === 'update') {
  wb = spec.operation === 'update' ? await SpreadsheetFile.importXlsx(await FileBlob.load(spec.path)) : Workbook.create();
  const existing = new Set((await wb.inspect({kind:'sheet',include:'name',maxChars:20000})).ndjson.split('\n').filter(Boolean).map(line=>JSON.parse(line)).filter(s=>s.kind==='sheet').map(s=>s.name));
  for (const s of spec.sheets) {
    if (!existing.has(s.name)) wb.worksheets.add(s.name);
    else wb.worksheets.getItem(s.name).getUsedRange().clear({applyTo:'all'});
  }
  for (const s of spec.sheets) {
    const sheet = wb.worksheets.getItem(s.name);
    sheet.showGridLines = false;
    const cols = Math.max(...s.rows.map(r => r.length));
    const rows = s.rows.map(r => Array.from({length: cols}, (_, i) => {
      const v = r[i] ?? null;
      return v && typeof v === 'object' && v.date ? new Date(v.date) : v;
    }));
    const range = sheet.getRangeByIndexes(0, 0, rows.length, cols);
    range.values = rows;
    for (let r = 0; r < s.rows.length; r++) {
      for (let c = 0; c < s.rows[r].length; c++) {
        if (s.rows[r][c]?.date) sheet.getCell(r,c).setNumberFormat('yyyy-mm-dd');
      }
    }
    range.format.font = {name: 'Arial', size: 11};
    range.format.verticalAlignment = 'center';
    range.format.columnWidth = 22;
    range.format.rowHeight = 28;
    sheet.getRangeByIndexes(0, 0, 1, cols).format = {
      fill: '#243746', font: {bold: true, color: '#FFFFFF'}, wrapText: true,
    };
    for (const f of s.formulas ?? []) {
      sheet.getRange(f.cell).formulas = [[f.formula]];
      if (f.fill_down_to) {
        const start=/^([A-Z]+)([1-9][0-9]*)$/.exec(f.cell),end=/^([A-Z]+)([1-9][0-9]*)$/.exec(f.fill_down_to);
        if (!start||!end||start[1]!==end[1]||Number(end[2])<Number(start[2])||Number(end[2])>200) throw new Error('fill_down_to must stay in the same column within row 200');
        sheet.getRange(`${f.cell}:${f.fill_down_to}`).fillDown();
      }
    }
    for (const f of s.formats ?? []) sheet.getRange(f.range).setNumberFormat(f.format);
    for (let i = 0; i < cols; i++) {
      const width = s.widths?.[i] ?? 22;
      const col = sheet.getRangeByIndexes(0, i, rows.length, 1);
      col.format.columnWidth = Math.min(100, Math.max(12, width));
      col.format.wrapText = true;
    }
    range.format.autofitRows();
  }
  wb.recalculate();
  // Cross-sheet formulas have values only after every sheet is populated.
  // Fit row heights after calculation so linked evidence text is not clipped.
  for (const s of spec.sheets) wb.worksheets.getItem(s.name).getUsedRange().format.autofitRows();
  await fs.mkdir(path.dirname(spec.path), {recursive:true});
  const exported = path.join(scratch,'export.xlsx');
  await (await SpreadsheetFile.exportXlsx(wb)).save(exported);
  await fs.copyFile(exported,spec.path);
  await fs.mkdir(spec.preview_dir, {recursive:true});
  for (let i = 0; i < spec.sheets.length; i++) {
    const s = spec.sheets[i];
    const preview = await wb.render({sheetName:s.name, autoCrop:'all', scale:1, format:'png'});
    await fs.writeFile(path.join(spec.preview_dir, `${i}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
} else {
  const copied = path.join(scratch,'read.xlsx');
  await fs.copyFile(spec.path,copied);
  wb = await SpreadsheetFile.importXlsx(await FileBlob.load(copied));
}
const result = await wb.inspect({kind:'workbook,sheet,table', maxChars:60000,
  tableMaxRows:200, tableMaxCols:30, tableMaxCellChars:1500});
const errors = await wb.inspect({kind:'match', searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',
  options:{useRegex:true,maxResults:100}, maxChars:4000});
console.log(JSON.stringify({inspection:result.ndjson, formula_errors:errors.ndjson}));
