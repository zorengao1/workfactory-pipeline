"""Trusted PDF/DOCX reader and structured builder. No model code is executed."""
import json
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile
import xml.etree.ElementTree as ET


def inspect(path):
    if path.suffix == '.pdf':
        from pypdf import PdfReader
        pages = PdfReader(path).pages
        return {'pages':[{'page':i+1,'text':p.extract_text()} for i,p in enumerate(pages)]}
    if path.suffix == '.docx':
        from docx import Document
        doc = Document(path)
        return {'paragraphs':[p.text for p in doc.paragraphs],
                'tables':[[[c.text for c in r.cells] for r in t.rows] for t in doc.tables]}
    if path.suffix == '.pptx':
        with ZipFile(path) as z:
            names=sorted((n for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')),
                         key=lambda n:int(Path(n).stem[5:]))
            return {'slides':[{'slide':i+1,'text':list(ET.fromstring(z.read(n)).itertext())}
                              for i,n in enumerate(names)]}
    raise ValueError('Unsupported document format')


def create(path, content, runtime):
    sections=content.get('sections',[])
    if not content.get('title') or not sections:
        raise ValueError('A title and nonempty sections are required')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix == '.docx':
        from docx import Document
        from docx.shared import Pt, Inches
        from docx.oxml.ns import qn
        from docx.shared import RGBColor
        doc=Document()
        for border in doc.styles.element.xpath('.//w:pBdr'):
            border.getparent().remove(border)
        font=runtime.get('document_font')
        if not font:raise ValueError('Configure document_font with Chinese glyph coverage')
        for name in ('Normal','Title','Heading 1','Heading 2'):
            style=doc.styles[name];style.font.name=font;style.font.color.rgb=RGBColor(0,0,0)
            style.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),font)
        doc.styles['Normal'].font.size=Pt(11)
        doc.sections[0].left_margin=Inches(.85)
        doc.sections[0].right_margin=Inches(.85)
        doc.add_paragraph(content['title'],'Title')
        for section in sections:
            if section.get('heading'):doc.add_heading(section['heading'],level=1)
            for paragraph in section.get('paragraphs',[]):doc.add_paragraph(str(paragraph))
            rows=section.get('table',[])
            if rows:
                table=doc.add_table(rows=0,cols=max(map(len,rows)))
                table.style='Light Shading Accent 1'
                for row in rows:
                    cells=table.add_row().cells
                    for cell,value in zip(cells,row):cell.text=str(value)
        doc.save(path)
    elif path.suffix == '.pdf':
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib import colors
        font_file=runtime.get('pdf_font_file')
        if not font_file:raise ValueError('Configure pdf_font_file with embeddable Chinese font')
        pdfmetrics.registerFont(TTFont('DocumentFont',font_file))
        styles=getSampleStyleSheet()
        for style in styles.byName.values():style.fontName='DocumentFont'
        def p(value,style='BodyText'):return Paragraph(escape(str(value)),styles[style])
        flow=[p(content['title'],'Title'),Spacer(1,14)]
        for section in sections:
            if section.get('heading'):flow.append(p(section['heading'],'Heading2'))
            flow.extend(p(value) for value in section.get('paragraphs',[]))
            rows=section.get('table',[])
            if rows:
                columns=max(map(len,rows))
                table=Table([[p(v) for v in row]+[p('')]*(columns-len(row)) for row in rows],
                            colWidths=[480/columns]*columns,repeatRows=1)
                table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef2f6')),
                                          ('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
                flow.append(table)
            flow.append(Spacer(1,12))
        SimpleDocTemplate(str(path),leftMargin=55,rightMargin=55).build(flow)
    else:raise ValueError('Use presentation tool for PPTX creation')


if __name__=='__main__':
    spec=json.loads(Path(sys.argv[1]).read_text())
    path=Path(spec['path'])
    if spec['operation']=='create':create(path,spec['content'],spec.get('runtime',{}))
    print(json.dumps(inspect(path),ensure_ascii=False))
