const docx=require('docx'), fs=require('fs'); const R=require('../app/report_module.js');
const D=JSON.parse(fs.readFileSync('../data/pipeline_output.json'));
const blocks=R.buildSection(D); const doc=R.toDocx(blocks,docx,'Protected Species Section');
docx.Packer.toBuffer(doc).then(b=>{fs.writeFileSync('../data/SAFE_3.3.2_Protected_Species_Section.docx',b); fs.writeFileSync('../data/SAFE_3.3.2_Protected_Species_Section.html',R.toHTML(blocks,'Protected Species Section')); console.log('docx bytes',b.length,'blocks',blocks.length); console.log(R.aggregate(D).findings.join('\n'));});
