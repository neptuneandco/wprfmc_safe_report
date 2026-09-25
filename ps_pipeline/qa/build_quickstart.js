const docx=require('docx'), fs=require('fs');
const {Document,Packer,Paragraph,TextRun,Table,TableRow,TableCell,HeadingLevel,WidthType,BorderStyle,ShadingType,ImageRun,LevelFormat,AlignmentType,Footer}=docx;
const navy='21295C', ocean='065A82', slate='5A6C7D', mist='DDE7EE';
const P=(t,o={})=>new Paragraph({children:[new TextRun({text:t,size:o.size||22,bold:o.bold,color:o.color||'333333',italics:o.italics})],spacing:{after:o.after??100},...(o.bullet?{numbering:{reference:'bul',level:0}}:{})});
const H=(t,l)=>new Paragraph({heading:l===1?HeadingLevel.HEADING_1:HeadingLevel.HEADING_2,children:[new TextRun(t)]});
const steps=[['1','Load this year\'s data','PIFSC emails you one file, pipeline_output.json. Open the app, go to step 1, click "Load this year\'s file" and choose it. Every page updates. (Until then the app shows example data.)'],
 ['2','See which species look unusual','Each species card shows this year\'s count against a typical year. Orange = flagged as unusually high. Click a card for a plain-language reading of what the numbers say.'],
 ['3','Answer the two expert questions','For each flagged species: Did the fleet change gear or method this year? Is this a strong year class? Click Yes / No / Not sure. The checklist then names the most likely explanation and writes it into the species paragraph.'],
 ['4','Check the report tables','Tables 2, 2b and 2c exactly as they will print. Hover a column heading to see what it means. If a number looks wrong, tell PIFSC rather than editing it.'],
 ['5','Edit the species paragraphs','Every species has a draft paragraph. Flagged species come first. Edit freely — add what you know about the fishery, the ocean and the population.'],
 ['6','Create the report section','Click "Create Word document" or "Create Google Doc". You get section 3.3.2 with the key findings, your paragraphs, the tables and a methods note.']];
const border={style:BorderStyle.SINGLE,size:4,color:mist}; const B={top:border,bottom:border,left:border,right:border};
const W=9360; const cw=[900,2600,5860];
const rows=steps.map(([n,t,d])=>new TableRow({children:[
  new TableCell({borders:B,width:{size:cw[0],type:WidthType.DXA},shading:{fill:navy,type:ShadingType.CLEAR,color:'auto'},verticalAlign:'center',children:[new Paragraph({alignment:AlignmentType.CENTER,children:[new TextRun({text:n,size:40,color:'FFFFFF',font:'Georgia'})]})]}),
  new TableCell({borders:B,width:{size:cw[1],type:WidthType.DXA},margins:{top:80,bottom:80,left:120,right:120},children:[new Paragraph({children:[new TextRun({text:t,bold:true,color:navy,size:22})]})]}),
  new TableCell({borders:B,width:{size:cw[2],type:WidthType.DXA},margins:{top:80,bottom:80,left:120,right:120},children:[new Paragraph({children:[new TextRun({text:d,size:20,color:'333333'})]})]})]}));
const logo=fs.readFileSync('/mnt/skills/plugins/neptune-brand-theme/assets/neptune_logo_transparent.png');
const doc=new Document({creator:'Neptune',title:'Quick start — Protected Species Decision Support',
  numbering:{config:[{reference:'bul',levels:[{level:0,format:LevelFormat.BULLET,text:'\u2022',alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:540,hanging:270}}}}]}]},
  styles:{default:{document:{run:{font:'Calibri',size:22}}},paragraphStyles:[
    {id:'Heading1',name:'Heading 1',basedOn:'Normal',next:'Normal',quickFormat:true,run:{size:44,bold:true,color:navy,font:'Calibri'},paragraph:{spacing:{before:0,after:80}}},
    {id:'Heading2',name:'Heading 2',basedOn:'Normal',next:'Normal',quickFormat:true,run:{size:26,bold:true,color:navy,font:'Calibri'},paragraph:{spacing:{before:240,after:100}}}]},
  sections:[{properties:{page:{size:{width:12240,height:15840},margin:{top:1100,bottom:1000,left:1440,right:1440}}},
    footers:{default:new Footer({children:[new Paragraph({alignment:AlignmentType.RIGHT,children:[new ImageRun({type:'png',data:logo,transformation:{width:86,height:22}})]})]})},
    children:[
      new Paragraph({children:[new TextRun({text:'SAFE REPORT · PROTECTED SPECIES SECTION',size:18,bold:true,color:'F18F01',characterSpacing:40})],spacing:{after:60}}),
      H('Quick start: putting the section together',1),
      P('A six-step tool for building section 3.3.2 of the Pelagic SAFE report from the year\'s observer summaries. No software knowledge is needed; you review, judge and write, and the tool does the arithmetic and the document.',{color:slate,after:200}),
      new Table({width:{size:W,type:WidthType.DXA},columnWidths:cw,rows}),
      H('Three things to know',2),
      P('The flags. High means this year\'s count is unusually high compared with that species\' own past years and needs explaining in the report. Typical means within the normal range. Low means unusually few.',{bullet:1}),
      P('The numbers are not yours to edit. Every figure traces back to the summary tables. If something looks wrong, note the species and table and send it to PIFSC; they re-run the pipeline and send a new file.',{bullet:1}),
      P('Technical details are hidden by default. The "Show technical details" switch at the bottom of the left-hand menu reveals the statistics for analysts. Pages A and B (statistics and take-limit comparison) are optional.',{bullet:1}),
      H('Who does what',2),
      P('PIFSC: runs the data pipeline each year and sends the pipeline_output.json file. Observer records never leave NOAA — the file holds only yearly summaries.',{bullet:1}),
      P('Council staff: load the file, review the flags, answer the expert questions, edit the paragraphs, create the document.',{bullet:1}),
      P('Neptune / statistics team: maintains the pipeline and the method notes; validates the placeholder values before Council use.',{bullet:1}),
      P('Glossary: the last item in the left-hand menu defines every term used in the tool in plain language.',{color:slate,italics:true,after:0})]}]});
Packer.toBuffer(doc).then(b=>{fs.writeFileSync('../data/Quick_Start_Guide.docx',b); console.log('quickstart bytes',b.length);});
