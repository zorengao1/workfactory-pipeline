import json
from pathlib import Path
from openpyxl import Workbook, load_workbook
from docx import Document
from pptx import Presentation
from reportlab.pdfgen import canvas
from pypdf import PdfReader
out=Path('/task/outputs');out.mkdir(exist_ok=True)
w=Workbook();w.active.append(['quantity','price']);w.active.append([3,7]);w.save(out/'sample.xlsx')
d=Document();d.add_paragraph('WorkFactory smoke 21');d.save(out/'sample.docx')
p=Presentation();slide=p.slides.add_slide(p.slide_layouts[1]);slide.shapes.title.text='WorkFactory smoke 21';p.save(out/'sample.pptx')
c=canvas.Canvas(str(out/'sample.pdf'));c.drawString(70,700,'WorkFactory smoke 21');c.save()
assert load_workbook(out/'sample.xlsx').active['B2'].value==7
assert '21' in Document(out/'sample.docx').paragraphs[0].text
assert '21' in Presentation(out/'sample.pptx').slides[0].shapes.title.text
assert '21' in PdfReader(out/'sample.pdf').pages[0].extract_text()
print(json.dumps({'formats':['xlsx','docx','pptx','pdf'],'readback':'passed'}))
