// Trusted editable presentation builder. Specs contain data, never executable code.
import fs from 'node:fs/promises';
import path from 'node:path';
import { Presentation, PresentationFile } from '@oai/artifact-tool';
const spec=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const content=spec.content;
if (!content.slides?.length) throw new Error('Nonempty slides required');
const deck=Presentation.create({slideSize:{width:1280,height:720}});
for (const data of content.slides) {
  if (!data.title || !Array.isArray(data.paragraphs)) throw new Error('Each slide needs title and paragraphs');
  const slide=deck.slides.add();
  slide.background.fill='#ffffff';
  function text(value,top,height,size,bold=false) {
    const shape=slide.shapes.add({geometry:'textbox',position:{left:72,top,width:1136,height},
      fill:'none',line:{fill:'none',width:0}});
    shape.text=value;
    shape.text.style={fontFamily:'Arial',fontSize:size,bold,color:'#182230'};
  }
  text(data.title,50,100,44,true);
  text(data.paragraphs.join('\n\n'),170,475,28);
}
await fs.mkdir(spec.preview_dir,{recursive:true});
for (const [index,slide] of deck.slides.items.entries()) {
  const png=await deck.export({slide,format:'png',scale:1});
  await fs.writeFile(path.join(spec.preview_dir,`${index+1}.png`),new Uint8Array(await png.arrayBuffer()));
}
await fs.mkdir(path.dirname(spec.path),{recursive:true});
await (await PresentationFile.exportPptx(deck)).save(spec.path);
console.log(JSON.stringify({slides:content.slides.length,rendered:true}));
