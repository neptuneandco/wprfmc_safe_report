/* report_module.js — builds the SAFE protected-species section from pipeline_output.json.
   Used unchanged in the browser (app) and in node (sample build). No DOM access. */
(function(root){
const R = {};
const f = (v,d=1)=> (v===null||v===undefined||Number.isNaN(v)) ? '—' : (typeof v==='number'? v.toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d}) : String(v));
const sg = (v,d=2)=> (v>0?'+':'')+f(v,d);
const mean = a => a.reduce((s,v)=>s+v,0)/a.length;

/* ---------- data aggregation chapter ------------------------------------- */
R.aggregate = function(D){
  const T2=D.table2_interactions, T2b=D.table2b_rate_spatial, T2c=D.table2c_ocean, B=D.bayes, ITS=D.its||[], CZ=D.causal||[], N=D.narratives||[];
  const cur=D.meta.current_year;
  const flagged=T2.filter(r=>r.flag==='High'), low=T2.filter(r=>r.flag==='Low');
  const gatesFired = r => Object.entries(r.gates||{}).filter(([k,v])=>v).map(([k])=>k);
  const aboveMedian=T2.filter(r=>r.current>r.median), increasing=T2.filter(r=>r.trend==='Increasing');
  const rateAgree=T2.filter(r=>{const rb=T2b.find(x=>x.species_code===r.species_code); return Math.sign(r.robust_anomaly)===Math.sign(rb.rate_robust_anomaly);});
  const bigShift=T2b.filter(r=>r.centroid_shift_km>250).sort((a,b)=>b.centroid_shift_km-a.centroid_shift_km);
  const outside=T2b.filter(r=>r.pct_outside_hist90>10);
  const vars=[...new Set(T2c.map(o=>o.variable))];
  const ocean=vars.map(v=>{const rows=T2c.filter(o=>o.variable===v); const hi=rows.filter(o=>o.interaction_percentile>=75).length, lo=rows.filter(o=>o.interaction_percentile<=25).length; const selHi=rows.filter(o=>o.selection_percentile>=90).length, selLo=rows.filter(o=>o.selection_percentile<=10).length;
    return {variable:v, meanPct:mean(rows.map(o=>o.interaction_percentile)), hi, lo, n:rows.length, selExtreme:selHi+selLo, direction: hi>lo?'high':lo>hi?'low':'mixed'};});
  const beyond=T2.filter(r=>{const b=B.find(x=>x.species_code===r.species_code); return r.current>b.posterior_pred_q95||r.current<b.posterior_pred_q05;});
  const fallbacks=T2b.filter(r=>/fallback|error/i.test(r.trend_model_flag||''));
  const itsRows=ITS.filter(i=>i.annual_its); const itsAlert=itsRows.filter(i=>i.alert); const itsHigh=itsRows.filter(i=>i.pct_of_limit>=75);
  const eff=(D.context&&D.context.spatial_effort)||[]; const effTop=[...eff].sort((a,b)=>Math.abs(b.shift_pct_points)-Math.abs(a.shift_pct_points))[0];
  const clim=(D.context&&D.context.climate_indicators)||[];
  const demo=(D.context&&D.context.demographics)||[];
  const gear=(D.context&&D.context.gear)||[];
  const beh=(D.context&&D.context.fisher_behavior)||[];
  const findings=[];
  findings.push(flagged.length? `${flagged.length} of ${T2.length} monitored species ${flagged.length===1?'is':'are'} flagged High in ${cur}: ${flagged.map(r=>`${r.species} (${r.current} vs median ${f(r.median,0)}; gates: ${gatesFired(r).join(', ')})`).join('; ')}.` : `No species is flagged High in ${cur}; all counts fall within their historical distributions.`);
  if(low.length) findings.push(`${low.map(r=>r.species).join(', ')} ${low.length===1?'is':'are'} flagged Low (robust anomaly ≤ −2).`);
  findings.push(`${aboveMedian.length} of ${T2.length} species are above their historical median and ${increasing.length} show an increasing long-run slope; the interaction-rate anomaly agrees in sign with the count anomaly for ${rateAgree.length} of ${T2.length}, so most of the change is not an artefact of effort.`);
  findings.push(beyond.length? `The current count falls outside the Gamma-Poisson posterior predictive 90% interval for ${beyond.map(r=>{const b=B.find(x=>x.species_code===r.species_code); return `${r.species} (${r.current>b.posterior_pred_q95?"above":"below"})`;}).join(', ')}; every other current count sits inside its interval.` : `No current count falls outside its Gamma-Poisson posterior predictive 90% interval.`);
  findings.push(bigShift.length? `Interaction centroids moved more than 250 km for ${bigShift.map(r=>`${r.species} (${f(r.centroid_shift_km,0)} km)`).join(', ')}${outside.length?`; ${outside.map(r=>`${f(r.pct_outside_hist90,1)}% of ${r.species.toLowerCase()} interactions`).join(' and ')} fell outside the historical 90% area`:''}. Spatial redistribution, not abundance, is the leading explanation where the rate anomaly is modest.` : 'Interaction centroids stayed within 250 km of their historical positions for every species.');
  const oc=ocean.filter(o=>o.hi>=Math.ceil(o.n*0.6)||o.lo>=Math.ceil(o.n*0.6)); if(oc.length) findings.push(`A coherent ocean regime is visible at interaction sets: ${oc.map(o=>`${o.variable} ${o.direction} for ${o.direction==='high'?o.hi:o.lo} of ${o.n} species (mean ${f(o.meanPct,0)}th percentile)`).join('; ')}.`);
  const selx=ocean.filter(o=>o.selExtreme>0); if(selx.length) findings.push(`Fleet selection anomalies (interaction-set environment minus fleet-wide environment) are at historical extremes for ${selx.map(o=>`${o.variable} (${o.selExtreme} species)`).join(', ')}, indicating the fleet fished a different habitat envelope than usual rather than the ocean alone changing.`);
  if(effTop) findings.push(`Fleet effort share changed most in the ${effTop.stratum} stratum (${sg(effTop.shift_pct_points,1)} points; ${effTop.operational_driver}).`);
  if(itsRows.length) findings.push(itsAlert.length? `ITS running-sum alert for ${itsAlert.map(i=>`${i.species} (${f(i.pct_of_limit,0)}% of window limit, P(exceed) ${f(i.p_exceed_before_close,2)})`).join(', ')}.` : `No ITS running-sum alert; ${itsHigh.length? itsHigh.map(i=>`${i.species} stands at ${f(i.pct_of_limit,0)}% of its window limit after ${i.years_elapsed} of ${i.window_years} years`).join(', ')+'.' : 'all tracked species are below 75% of their window limits.'}`);
  if(fallbacks.length) findings.push(`Trend-model diagnostics: negative-binomial fitting fell back to Poisson for ${fallbacks.map(r=>r.species).join(', ')}; these annual-percent-change values carry wider uncertainty than reported.`);
  const unclear=CZ.filter(c=>c.higher_than_normal && !c.expected_from_trend && !(c.fishery_changed&&c.shifted_into_core));
  if(unclear.length) findings.push(`Causal diagnosis for ${unclear.map(c=>c.species).join(', ')} cannot be closed from the data alone; it needs expert input on gear/method change and year-class strength.`);
  const crossTable = T2.map(r=>{const rb=T2b.find(x=>x.species_code===r.species_code); const b=B.find(x=>x.species_code===r.species_code); const it=ITS.find(x=>x.species_code===r.species_code)||{}; const n=N.find(x=>x.species_code===r.species_code)||{}; const oc=T2c.filter(o=>o.species_code===r.species_code); const sig=oc.filter(o=>o.interaction_percentile>=90||o.interaction_percentile<=10).map(o=>o.variable+(o.interaction_percentile>=90?' ↑':' ↓')).join(', ')||'none';
    return {species:r.species, flag:r.flag, gates:gatesFired(r).join(', ')||'none', count:`${r.current} (P${f(r.percentile,0)})`, rate:`${sg(rb.rate_robust_anomaly)} (P${f(rb.rate_percentile,0)})`, trend:`${sg(rb.annual_pct_change,1)}%/yr`, shift:`${f(rb.centroid_shift_km,0)} km`, pred:`${b.posterior_pred_q05}–${b.posterior_pred_q95}`, ocean:sig, its: it.annual_its? `${f(it.pct_of_limit,0)}%`:'n/a', branch:n.causal_branch||'—'};});
  return {cur, flagged, low, findings, ocean, crossTable, bigShift, itsRows, effTop, clim, demo, gear, beh, fallbacks, beyond};
};

/* ---------- section builder (block model) --------------------------------- */
R.buildSection = function(D, narrativeOverride){
  const A=R.aggregate(D); const cur=A.cur; const blocks=[];
  const H=(l,t)=>blocks.push({type:'h'+l,text:t}), P=t=>blocks.push({type:'p',text:t}), UL=items=>blocks.push({type:'bullets',items}), NOTE=t=>blocks.push({type:'note',text:t});
  const TBL=(caption,cols,rows)=>blocks.push({type:'table',caption,cols,rows});
  H(1,`3.3.2 Protected Species Interactions — Hawaii Longline Fisheries, ${cur}`);
  NOTE(`Generated ${D.meta.generated} from the automated SAFE pipeline (${D.meta.mode||'test'} mode). ${D.meta.data_note||''} Narratives are drafts requiring analyst review.`);
  H(2,'3.3.2.1 Data aggregation and key findings');
  P(`This chapter aggregates the results of the three summary tables (Tables 2, 2b, 2c), the Bayesian anomaly check, the incidental take statement (ITS) tracker and the multi-disciplinary context reviewed by the working group, to characterise protected-species interactions in the ${cur} fishing year. Anomalies are judged with an OR gate (${D.meta.decision_rule}).`);
  H(3,'Key findings'); UL(A.findings);
  H(3,'Cross-species aggregation');
  TBL(`Aggregation of anomaly evidence by species, ${cur}.`, ['Species','Flag','Gates fired','Count (percentile)','Rate anomaly','Trend','Centroid shift','Predictive 90%','Ocean extremes at sets','ITS window used','Causal branch'],
      A.crossTable.map(r=>[r.species,r.flag,r.gates,r.count,r.rate,r.trend,r.shift,r.pred,r.ocean,r.its,r.branch]));
  H(3,'Ocean regime at interaction sets');
  TBL('Direction of environmental conditions at interaction sets across species (share of species at or beyond the 75th / 25th percentile of their own history).', ['Variable','Mean percentile','Species high (≥75th)','Species low (≤25th)','Species with extreme selection anomaly','Reading'],
      A.ocean.map(o=>[o.variable,f(o.meanPct,0),`${o.hi} of ${o.n}`,`${o.lo} of ${o.n}`,String(o.selExtreme),o.direction==='mixed'?'no coherent signal':`${o.direction} across the fishery`]));
  if(A.clim.length) TBL('Basin-scale climate indicators.', ['Indicator','Value','State','Correlation with interactions','Mechanism'], A.clim.map(c=>[c.indicator,c.value==null?'—':f(c.value,2),c.state,c.interaction_correlation,c.mechanism]));
  H(3,'Fleet dynamics, gear and fisher behaviour');
  const eff=(D.context&&D.context.spatial_effort)||[]; if(eff.length) TBL('Fleet effort share by stratum, baseline vs. current.', ['Stratum','Baseline %','Current %','Shift (pts)','Operational driver','Species overlap'], eff.map(e=>[e.stratum,f(e.baseline_effort_share_pct,1),f(e.current_effort_share_pct,1),sg(e.shift_pct_points,1),e.operational_driver,e.species_overlap]));
  if(A.gear.length) TBL('Gear configuration and interaction outcomes.', ['Gear variable','Adoption %','Interactions','CPUE per 1,000 hooks','At-vessel mortality %','Finding'], A.gear.map(g=>[g.gear_variable,g.fleet_adoption_pct==null?'—':f(g.fleet_adoption_pct,0),g.observed_interactions==null?'—':String(g.observed_interactions),g.interaction_cpue_per_1000_hooks==null?'—':f(g.interaction_cpue_per_1000_hooks,4),g.at_vessel_mortality_pct==null?'—':f(g.at_vessel_mortality_pct,1),g.finding]));
  if(A.beh.length) TBL('Post-interaction fisher behaviour.', ['Interactions on trip','Distance to next set (km)','Post-move interaction probability','Trips','Fleet response'], A.beh.map(b=>[b.cumulative_interactions_on_trip,b.avg_distance_to_next_set_km==null?'—':f(b.avg_distance_to_next_set_km,1),b.post_move_interaction_probability,b.n_trips==null?'—':String(b.n_trips),b.fleet_response]));
  H(3,'Demographic composition of take');
  if(A.demo.length) TBL('Size-class composition, mortality and population context (illustrative).', ['Species / DPS','Size class','% of takes','At-vessel mortality %','Post-release mortality %','Est. mortalities / yr','Population context'], A.demo.map(d=>[d.dps,d.size_class,f(d.pct_of_takes,0),f(d.at_vessel_mortality_pct,1),f(d.post_release_mortality_pct,1),d.est_total_mortalities_per_yr==null?'—':f(d.est_total_mortalities_per_yr,1),d.population_trend_note||'']));
  H(3,'Incidental take statement status');
  if(A.itsRows.length) TBL('ITS running-sum tracker (fleet-expanded take; ITS values illustrative).', ['Species','Authority','Annual ITS','Window','Years elapsed','Cumulative expanded take','Window limit','% of limit','P(exceed before close)','Alert'], A.itsRows.map(i=>[i.species,i.authority,String(i.annual_its),`${i.window_years} yr from ${i.window_start}`,String(i.years_elapsed),String(i.cumulative),String(i.window_limit),f(i.pct_of_limit,0),f(i.p_exceed_before_close,3),i.alert?'Yes':'No']));
  H(3,'Data gaps and validation needs');
  UL(['ITS values, β reporting-bias scaler, environmental-sensitivity coefficient, gear multipliers and size-class shares are placeholders pending SME validation.','Gear/method change and year-class strength are not observable from the aggregated tables and are required to close the causal diagnosis.','An aggregated species × year × size-class view from LOTUS is needed to compute demographic composition rather than transcribe it.', ...(A.fallbacks.length?[`Negative-binomial trend fits fell back to Poisson for ${A.fallbacks.map(r=>r.species).join(', ')}.`]:[])]);
  H(2,'3.3.2.2 Species accounts');
  (D.narratives||[]).forEach(n=>{ H(3,`${n.species} — ${n.flag}`); P((narrativeOverride&&narrativeOverride[n.species_code])||n.narrative); NOTE(`Source: ${n.source}. ${n.provenance||''}`); });
  H(2,'3.3.2.3 Summary tables');
  TBL(`Table 2. Observed interactions, ${cur} vs. historical distribution.`, ['Species','Current','Mean','Median','P10','P90','Percentile','Robust anomaly','N years','Trend slope','Trend','Flag'],
      D.table2_interactions.map(r=>[r.species,String(r.current),f(r.mean,1),f(r.median,0),f(r.p10,1),f(r.p90,1),f(r.percentile,0),sg(r.robust_anomaly),String(r.n_years),f(r.trend_slope,2),r.trend,r.flag]));
  TBL('Table 2b. Interaction rate per observed set, trend model and centroid shift.', ['Species','Rate','Hist. median rate','Hist. P90 rate','Rate percentile','Rate robust anomaly','Annual % change','Model','Model flag','Trend yrs','Centroid shift km','% outside hist. 90%'],
      D.table2b_rate_spatial.map(r=>[r.species,f(r.current_rate,4),f(r.hist_median_rate,4),f(r.hist_p90_rate,4),f(r.rate_percentile,0),sg(r.rate_robust_anomaly),sg(r.annual_pct_change,1),r.trend_model,r.trend_model_flag,String(r.trend_years),f(r.centroid_shift_km,0),f(r.pct_outside_hist90,1)]));
  TBL('Table 2c. Environment at interaction sets vs. fleet-wide environment.', ['Species','Variable','Current at sets','Hist. median','Abs. anomaly','Current fleet','Selection anomaly','Selection shift','Interaction %ile','Selection %ile'],
      D.table2c_ocean.map(o=>[o.species,o.variable,f(o.current_interaction_env,3),f(o.hist_interaction_median,3),sg(o.absolute_anomaly,3),f(o.current_fleet_env,3),sg(o.current_selection_anomaly,3),sg(o.selection_shift,3),f(o.interaction_percentile,0),f(o.selection_percentile,0)]));
  H(2,'Methods and provenance');
  P('Robust anomaly = (current − median) ÷ (1.4826 × MAD) over historical years. Percentile = share of historical years strictly below the current value. Trend = log-linear Poisson GLM with observed sets as offset, upgraded to negative binomial when Pearson dispersion exceeds 1.5. Bayesian check = Gamma-Poisson conjugate model with a method-of-moments prior; P(X ≥ current) evaluated by the negative-binomial–incomplete-beta identity. Flag = OR gate over the three tests.');
  UL((D.provenance||[]).map(p=>`${p.table_name}: ${p.source} (${p.confidentiality})`));
  return blocks;
};

/* ---------- renderers ------------------------------------------------------ */
R.toHTML = function(blocks, title){
  const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  const css=`body{font-family:Calibri,Arial,sans-serif;color:#333;font-size:11pt;line-height:1.4} h1{color:#21295C;font-size:18pt} h2{color:#21295C;font-size:14pt;margin-top:18pt} h3{color:#065A82;font-size:12pt;margin-top:12pt} table{border-collapse:collapse;font-size:9pt;margin:6pt 0 10pt} th{background:#DDE7EE;color:#21295C;text-align:left;padding:3pt 5pt;border:1px solid #B9C7D3} td{padding:3pt 5pt;border:1px solid #DDE7EE;vertical-align:top} caption{text-align:left;font-weight:bold;color:#21295C;font-size:9.5pt;margin-bottom:3pt} .note{color:#5A6C7D;font-size:9pt;font-style:italic}`;
  let h=`<!DOCTYPE html><html><head><meta charset="utf-8"><title>${esc(title)}</title><style>${css}</style></head><body>`;
  blocks.forEach(b=>{ if(b.type.startsWith('h')) h+=`<${b.type}>${esc(b.text)}</${b.type}>`; else if(b.type==='p') h+=`<p>${esc(b.text)}</p>`; else if(b.type==='note') h+=`<p class="note">${esc(b.text)}</p>`;
    else if(b.type==='bullets') h+=`<ul>${b.items.map(i=>`<li>${esc(i)}</li>`).join('')}</ul>`;
    else if(b.type==='table') h+=`<table><caption>${esc(b.caption)}</caption><tr>${b.cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr>${b.rows.map(r=>`<tr>${r.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</table>`; });
  return h+'</body></html>';
};
R.toDocx = function(blocks, docx, title){
  const {Document,Packer,Paragraph,TextRun,Table,TableRow,TableCell,HeadingLevel,WidthType,BorderStyle,ShadingType,AlignmentType,PageOrientation}=docx;
  const border={style:BorderStyle.SINGLE,size:4,color:'DDE7EE'}; const borders={top:border,bottom:border,left:border,right:border};
  const kids=[];
  blocks.forEach(b=>{
    if(b.type==='h1') kids.push(new Paragraph({heading:HeadingLevel.HEADING_1,children:[new TextRun(b.text)]}));
    else if(b.type==='h2') kids.push(new Paragraph({heading:HeadingLevel.HEADING_2,children:[new TextRun(b.text)]}));
    else if(b.type==='h3') kids.push(new Paragraph({heading:HeadingLevel.HEADING_3,children:[new TextRun(b.text)]}));
    else if(b.type==='p') kids.push(new Paragraph({children:[new TextRun(b.text)],spacing:{after:120}}));
    else if(b.type==='note') kids.push(new Paragraph({children:[new TextRun({text:b.text,italics:true,color:'5A6C7D',size:18})],spacing:{after:120}}));
    else if(b.type==='bullets') b.items.forEach(i=>kids.push(new Paragraph({children:[new TextRun(i)],bullet:{level:0},spacing:{after:60}})));
    else if(b.type==='table'){
      kids.push(new Paragraph({children:[new TextRun({text:b.caption,bold:true,color:'21295C',size:19})],spacing:{before:160,after:80}}));
      const W=13840; const cw=b.cols.map(()=>Math.floor(W/b.cols.length)); cw[cw.length-1]+=W-cw.reduce((a,c)=>a+c,0);
      const cell=(t,head,i)=>new TableCell({borders,width:{size:cw[i],type:WidthType.DXA},shading:head?{fill:'DDE7EE',type:ShadingType.CLEAR,color:'auto'}:undefined,margins:{top:40,bottom:40,left:70,right:70},children:[new Paragraph({children:[new TextRun({text:String(t??''),bold:!!head,color:head?'21295C':'333333',size:16})]})]});
      kids.push(new Table({width:{size:W,type:WidthType.DXA},columnWidths:cw,rows:[new TableRow({tableHeader:true,children:b.cols.map((c,i)=>cell(c,true,i))}),...b.rows.map(r=>new TableRow({children:r.map((c,i)=>cell(c,false,i))}))]}));
      kids.push(new Paragraph({children:[],spacing:{after:80}}));
    }
  });
  const doc=new Document({creator:'SAFE protected-species pipeline',title,
    styles:{default:{document:{run:{font:'Calibri',size:22,color:'333333'}}},
      paragraphStyles:[{id:'Heading1',name:'Heading 1',basedOn:'Normal',next:'Normal',quickFormat:true,run:{size:36,bold:true,color:'21295C',font:'Calibri'},paragraph:{spacing:{before:240,after:160}}},
                       {id:'Heading2',name:'Heading 2',basedOn:'Normal',next:'Normal',quickFormat:true,run:{size:28,bold:true,color:'21295C',font:'Calibri'},paragraph:{spacing:{before:280,after:120}}},
                       {id:'Heading3',name:'Heading 3',basedOn:'Normal',next:'Normal',quickFormat:true,run:{size:24,bold:true,color:'065A82',font:'Calibri'},paragraph:{spacing:{before:200,after:80}}}]},
    sections:[{properties:{page:{size:{width:12240,height:15840,orientation:PageOrientation.LANDSCAPE},margin:{top:1000,bottom:1000,left:1000,right:1000}}},children:kids}]});
  return Packer.toBlob ? doc : doc;   // caller packs (Packer.toBlob in browser, Packer.toBuffer in node)
};
root.PSReport = R;
})(typeof window!=='undefined'? window : (typeof globalThis!=='undefined'? globalThis : this));
if(typeof module!=='undefined') module.exports = globalThis.PSReport;
