import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.join(project, 'reports/native');
await fs.mkdir(out, {recursive:true});
const data = JSON.parse(await fs.readFile(path.join(project, 'reports/reporting/workbook_inputs.json'), 'utf8'));
const wb = Workbook.create();
const overview = wb.worksheets.add('Overview');
const review = wb.worksheets.add('Review capacity');
const stats = wb.worksheets.add('Statistics');
const source = wb.worksheets.add('Sources');
const guide = wb.worksheets.add('ReadMe');
const ink='#16324F', blue='#0369A1', sky='#0EA5E9', pale='#F0F9FF', muted='#52667A';
const policies=['optimized','risk_first','priority_per_minute','oldest_first'];
const names=['Constrained optimizer','Highest risk first','Priority per minute','Oldest approval first'];
const scenarios=[...new Set(data.scenarios.map(r=>r.scenario))];
const B=(s,a,v)=>s.getRange(a).values=[[v]];
const F=(s,a,v)=>s.getRange(a).formulas=[[v]];
const fx=(s,a,m)=>s.getRange(a).formulas=m;
const values=(s,a,m)=>s.getRange(a).values=m;
function sheet(s,range,title){
  s.showGridLines=false;
  s.getRange(range).format={font:{name:'Arial',size:10,color:ink},rowHeight:22,verticalAlignment:'center'};
  s.getRange('A:A').format.columnWidth=3;
  s.getRange('B:P').format.columnWidth=13;
  s.getRange('B2').values=[[title]];
  s.getRange('B2').format.font={name:'Arial',size:16,bold:true,color:ink};
  s.getRange('B3:P3').format.borders={bottom:{style:'thin',color:'#BAE6FD'}};
  s.tabColor=blue;
}
function header(s,address){s.getRange(address).format={fill:blue,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},
  horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:35,
  borders:{insideVertical:{style:'thin',color:'#FFFFFF'}}};}
function section(s,address,text){B(s,address,text);s.getRange(address).format.font={name:'Arial',size:12,bold:true,color:ink};}
function table(s,address,name){const t=s.tables.add(address,true,name);t.style='TableStyleLight9';return t;}
function chart(s,ranges,title,start,end,type='bar',percent=false){
  const c=s.charts.add(type,ranges.map(r=>s.getRange(r)));c.title=title;c.titleTextStyle.typeface='Arial';c.titleTextStyle.fontSize=13;
  c.setPosition(start,end);c.hasLegend=ranges.length>2;
  c.legend={position:'top',textStyle:{typeface:'Arial',fontSize:10}};
  c.xAxis={axisType:'textAxis',textStyle:{typeface:'Arial',fontSize:10}};
  c.yAxis={numberFormatCode:percent?'0.0%':'#,##0',numberFormatSourceLinked:false,textStyle:{typeface:'Arial',fontSize:10}};
  c.series.items.forEach((series,i)=>{series.fill=[sky,'#64748B','#0F766E'][i%3];if(type==='line')series.line={fill:sky,style:'solid',width:2};});
  return c;
}
sheet(overview,'B2:P75','Delivery operations');
sheet(review,'B2:P63','Review capacity');
sheet(stats,'B2:P40','Delivery associations');
sheet(source,'B2:Q918','Reporting inputs');source.tabColor='#CBD5E1';
sheet(guide,'B2:P44','Definitions and refresh');guide.tabColor='#94A3B8';
source.getRange('B:B').format.columnWidth=32;source.getRange('C:C').format.columnWidth=23;source.getRange('D:D').format.columnWidth=20;
source.getRange('E:Q').format.columnWidth=15;
B(source,'B4','Source: Olist public dataset, version 2. '+data.source);
B(source,'B5','Aggregates cover all 99,441 source orders. Operations run: '+data.operation_run);
const monthlyStart=8, monthlyEnd=monthlyStart+data.monthly.length-1;
values(source,`B7:H${monthlyEnd}`,[['Purchase month','Orders','Eligible','Late','Unknown outcome','Delivery days sum','Median days'],
  ...data.monthly.map(r=>[new Date(r.purchase_month),r.orders,r.eligible,r.late,r.unknown,r.delivered_days_sum,r.median_delivery_days])]);
source.getRange(`B8:B${monthlyEnd}`).setNumberFormat('mmm yyyy');source.getRange(`C8:F${monthlyEnd}`).setNumberFormat('#,##0');
source.getRange(`G8:H${monthlyEnd}`).setNumberFormat('#,##0.00');header(source,'B7:H7');table(source,`B7:H${monthlyEnd}`,'MonthlyInput');
const stateStart=42,stateEnd=stateStart+data.states.length-1;
values(source,`B41:F${stateEnd}`,[['Customer state','Orders','Eligible','Late','Delivery days sum'],
  ...data.states.map(r=>[r.state,r.orders,r.eligible,r.late,r.delivered_days_sum])]);
source.getRange(`C42:E${stateEnd}`).setNumberFormat('#,##0');source.getRange(`F42:F${stateEnd}`).setNumberFormat('#,##0.00');
header(source,'B41:F41');table(source,`B41:F${stateEnd}`,'StateInput');
const scenarioStart=76,scenarioEnd=scenarioStart+data.scenarios.length-1;
values(source,`B75:O${scenarioEnd}`,[['Executed scenario','Policy','Minutes / batch','Time multiplier','Batches','Candidates','Known candidate late','Selected orders','Minutes used','Selected unknown','Selected known late','Priority points','Selected known outcomes','Unused minutes'],
  ...data.scenarios.map(r=>[r.scenario,r.policy,r.capacity_minutes,r.cost_multiplier,r.batches,r.candidate_orders,r.candidate_known_late,
    r.selected_orders,r.used_minutes,r.selected_unknown_outcomes,r.selected_known_late,r.priority_points,r.selected_known_outcomes,r.unused_minutes])]);
header(source,'B75:O75');source.getRange(`D76:O${scenarioEnd}`).setNumberFormat('#,##0.00');table(source,`B75:O${scenarioEnd}`,'ScenarioInput');
const dailyStart=112,dailyEnd=dailyStart+data.daily.length-1;
values(source,`B111:P${dailyEnd}`,[['Scenario','Policy','Screening date','Minutes / batch','Time multiplier','Candidate orders','Candidate known late','Selected orders','Minutes used','Selected unknown','Selected known late','Priority points','Selected known outcomes','Unused minutes','Optimal (optimizer)'],
 ...data.daily.map(r=>[r.scenario,r.policy,new Date(r.batch_cutoff),r.capacity_minutes,r.cost_multiplier,r.candidate_orders,r.candidate_known_late,
 r.selected_orders,r.used_minutes,r.selected_unknown_outcomes,r.selected_known_late,r.priority_points,r.selected_known_outcomes,r.unused_minutes,
 r.policy==='optimized'?r.optimal:null])]);
header(source,'B111:P111');source.getRange(`D112:D${dailyEnd}`).setNumberFormat('dd mmm yyyy');
source.getRange(`E112:O${dailyEnd}`).setNumberFormat('#,##0.0');table(source,`B111:P${dailyEnd}`,'DailyInput');
values(source,'B904:P908',[['Contrast','Reference orders','Reference late','Exposed orders','Exposed late','Adjusted difference','CI low','CI high','Holm p','Excluded orders','Months','Week clusters','Day CI low','Day CI high','Eligible cohort'],
 ...data.contrasts.map(r=>[r.label,r.reference_orders,r.reference_late,r.exposed_orders,r.exposed_late,r.adjusted_difference,r.ci_low,r.ci_high,
 r.holm_p_value,r.excluded_from_contrast,r.months,r.clusters,r.day_cluster_ci_low,r.day_cluster_ci_high,r.eligible_orders])]);
header(source,'B904:P904');table(source,'B904:P908','StatisticalInput');
source.freezePanes.freezeRows(7);

B(overview,'B4','Historical Olist data, 2016â€“2018. Delivery percentages use eligible completed orders only.');
values(overview,'B6:C10',[['Delivery result','Value'],['Eligible deliveries',null],['Late deliveries',null],['Late rate',null],['Mean delivery days',null]]);
header(overview,'B6:C6');overview.getRange('B:B').format.columnWidth=23;
F(overview,'C7',`=SUM('Sources'!D${monthlyStart}:D${monthlyEnd})`);
F(overview,'C8',`=SUM('Sources'!E${monthlyStart}:E${monthlyEnd})`);
F(overview,'C9','=IF(C7=0,"n.a.",C8/C7)');
F(overview,'C10',`=IF(C7=0,"n.a.",SUM('Sources'!G${monthlyStart}:G${monthlyEnd})/C7)`);
overview.getRange('C7:C8').setNumberFormat('#,##0');overview.getRange('C9').setNumberFormat('0.00%');overview.getRange('C10').setNumberFormat('0.00');
values(overview,'F6:G9',[['Source coverage','Orders'],['All source orders',null],['Outside SLA cohort',null],['On-time deliveries',null]]);header(overview,'F6:G6');
overview.getRange('F:F').format.columnWidth=23;
F(overview,'G7',`=SUM('Sources'!C${monthlyStart}:C${monthlyEnd})`);
F(overview,'G8',`=SUM('Sources'!F${monthlyStart}:F${monthlyEnd})`);F(overview,'G9','=C7-C8');overview.getRange('G7:G9').setNumberFormat('#,##0');
const omStart=14,omEnd=omStart+data.monthly.length-1;
values(overview,'B13:F13',[['Purchase month','All orders','Eligible','Late','Late rate']]);header(overview,'B13:F13');
fx(overview,`B${omStart}:F${omEnd}`,data.monthly.map((r,i)=>{const sr=monthlyStart+i,or=omStart+i;return [
  `=TEXT('Sources'!B${sr},"mmm yy")`,`='Sources'!C${sr}`,`='Sources'!D${sr}`,`='Sources'!E${sr}`,`=IF(D${or}=0,"n.a.",E${or}/D${or})`];}));
overview.getRange(`C${omStart}:E${omEnd}`).setNumberFormat('#,##0');overview.getRange(`F${omStart}:F${omEnd}`).setNumberFormat('0.00%');
overview.getRange(`F${omStart}:F${omEnd}`).format.horizontalAlignment='right';
chart(overview,[`B13:B${omEnd}`,`E13:E${omEnd}`],'Late deliveries by purchase month','H13','P32','line',false);
values(overview,'B43:F43',[['Customer state','All orders','Eligible','Late','Late rate']]);header(overview,'B43:F43');
fx(overview,'B44:F70',data.states.map((r,i)=>{const sr=stateStart+i,or=44+i;return [`='Sources'!B${sr}`,`='Sources'!C${sr}`,`='Sources'!D${sr}`,`='Sources'!E${sr}`,`=IF(D${or}=0,"n.a.",E${or}/D${or})`];}));
overview.getRange('C44:E70').setNumberFormat('#,##0');overview.getRange('F44:F70').setNumberFormat('0.00%');
chart(overview,['B43:B51','F43:F51'],'Late rate: eight largest state cohorts','H43','P63','bar',true);

B(review,'B4','Executed August replay. Scenario results are saved Python optimizer runs, not live Excel optimization.');
B(review,'B6','Executed scenario');B(review,'C6','capacity_120_cost_1');review.getRange('C6').format.fill='#FEF3C7';
review.getRange('B:B').format.columnWidth=30;review.getRange('C:C').format.columnWidth=30;
review.getRange('D:P').format.columnWidth=14;
review.getRange('C6').dataValidation={rule:{type:'list',values:scenarios}};
B(review,'B7','Daily detail policy');B(review,'C7','optimized');review.getRange('C7').format.fill='#FEF3C7';
review.getRange('C7').dataValidation={rule:{type:'list',values:policies}};
B(review,'H6','Scenario inputs');header(review,'H6:K6');B(review,'H7','Minutes / batch');B(review,'H8','Time multiplier');B(review,'H9','Screening batches');
review.getRange('H6:K6').format.borders={preset:'none'};
const sm=(col,policy)=>`SUMIFS('Sources'!$${col}$${scenarioStart}:$${col}$${scenarioEnd},'Sources'!$B$${scenarioStart}:$B$${scenarioEnd},$C$6,'Sources'!$C$${scenarioStart}:$C$${scenarioEnd},${policy})`;
F(review,'K7','='+sm('D','"optimized"'));F(review,'K8','='+sm('E','"optimized"'));F(review,'K9','='+sm('F','"optimized"'));
values(review,'B12:I12',[['Policy','Reviewed','Minutes used','Unknown reviewed','Known late reviewed','Known late capture','Minutes utilization','Priority points']]);header(review,'B12:I12');
fx(review,'B13:I16',policies.map((p,i)=>{const r=13+i;return [null,'='+sm('I',`"${p}"`),'='+sm('J',`"${p}"`),'='+sm('K',`"${p}"`),
 '='+sm('L',`"${p}"`),`=IF(${sm('H',`"${p}"`)}=0,"n.a.",F${r}/${sm('H',`"${p}"`)})`,
 `=IF($K$7*$K$9=0,"n.a.",D${r}/($K$7*$K$9))`,'='+sm('M',`"${p}"`)];}));
values(review,'B13:B16',names.map(n=>[n]));review.getRange('C13:F16').setNumberFormat('#,##0');review.getRange('G13:H16').setNumberFormat('0.0%');review.getRange('I13:I16').setNumberFormat('#,##0.0');
B(review,'B18','Unknown outcomes consume capacity. Known late counts describe historical outcomes, not delays prevented.');
B(review,'B19','Review times are assumptions. Model probabilities are unreliable; August is a reused diagnostic.');
const dates=[...new Set(data.daily.map(r=>r.batch_cutoff))].sort();
values(review,'B22:G22',[['Screening date','Candidates','Reviewed','Minutes used','Unknown reviewed','Known late reviewed']]);header(review,'B22:G22');
values(review,`B23:B${22+dates.length}`,dates.map(d=>[new Date(d)]));review.getRange(`B23:B${22+dates.length}`).setNumberFormat('dd mmm yyyy');
const dm=(col,r)=>`SUMIFS('Sources'!$${col}$${dailyStart}:$${col}$${dailyEnd},'Sources'!$B$${dailyStart}:$B$${dailyEnd},$C$6,'Sources'!$C$${dailyStart}:$C$${dailyEnd},$C$7,'Sources'!$D$${dailyStart}:$D$${dailyEnd},$B${r})`;
fx(review,`C23:G${22+dates.length}`,dates.map((d,i)=>['G','I','J','K','L'].map(c=>'='+dm(c,23+i))));
review.getRange(`C23:G${22+dates.length}`).setNumberFormat('#,##0');
section(review,'I23','Simple staffing calculator');B(review,'I25','Pooled minutes');B(review,'K25',120);B(review,'I26','Minutes per review');B(review,'K26',4);
B(review,'I27','Review count limit');B(review,'K27',30);review.getRange('K25:K27').format.fill='#FEF3C7';
review.getRange('K25:K25').dataValidation={rule:{type:'whole',operator:'between',formula1:0,formula2:1440}};
review.getRange('K26:K26').dataValidation={rule:{type:'whole',operator:'between',formula1:1,formula2:120}};
review.getRange('K27:K27').dataValidation={rule:{type:'whole',operator:'between',formula1:0,formula2:1000}};
B(review,'I29','Uniform-cost capacity');
F(review,'K29','=IF(OR(NOT(ISNUMBER(K25)),NOT(ISNUMBER(K26)),NOT(ISNUMBER(K27)),K25<0,K26<=0,K27<0),"n.a.",MIN(K27,INT(K25/K26)))');
B(review,'I31','This bound recalculates in Excel.');B(review,'I32','It does not rerun the optimizer.');
review.getRange('I:I').format.columnWidth=28;review.getRange('K:K').format.columnWidth=18;
chart(review,['B12:B16','F12:F16'],'Known late outcomes offered review','I36','P54');
review.freezePanes.freezeRows(12);

stats.getRange('B:B').format.columnWidth=46;stats.getRange('C:K').format.columnWidth=14;stats.getRange('L:L').format.columnWidth=20;
B(stats,'B4','96,470 eligible completed orders. Separate exploratory contrasts adjusted for purchase month.');
B(stats,'B5','Week-clustered uncertainty. Holm correction across four tests. Associations do not establish causation.');
values(stats,'B8:L8',[['Comparison','Reference orders','Reference late rate','Exposed orders','Exposed late rate','Difference (pp)','95% CI low (pp)','95% CI high (pp)','Holm p','Excluded orders','Holm result']]);header(stats,'B8:L8');
fx(stats,'B9:L12',data.contrasts.map((r,i)=>{const sr=905+i,or=9+i;return [`='Sources'!B${sr}`,`='Sources'!C${sr}`,`='Sources'!D${sr}/C${or}`,
 `='Sources'!E${sr}`,`='Sources'!F${sr}/E${or}`,`='Sources'!G${sr}*100`,`='Sources'!H${sr}*100`,`='Sources'!I${sr}*100`,
 `='Sources'!J${sr}`,`='Sources'!K${sr}`,`=IF(J${or}<0.05,"Association detected","Inconclusive")`];}));
stats.getRange('B9:B12').format.wrapText=true;stats.getRange('B9:L12').format.rowHeight=38;
stats.getRange('C9:C12').setNumberFormat('#,##0');stats.getRange('E9:E12').setNumberFormat('#,##0');stats.getRange('D9:D12').setNumberFormat('0.00%');stats.getRange('F9:F12').setNumberFormat('0.00%');
stats.getRange('G9:I12').setNumberFormat('+0.00;-0.00;0.00');stats.getRange('J9:J12').setNumberFormat('0.00E+00');stats.getRange('K9:K12').setNumberFormat('#,##0');
B(stats,'B15','Intervals are marginal 95% intervals. Week clusters assume independence between weeks.');
B(stats,'B16','Distance contrast excludes incomplete geocoding and the 500â€“1,000 km band.');
B(stats,'B17','The small promise-window contrast is inconclusive under week-clustered uncertainty.');
B(stats,'B19','Month adjustment does not remove other confounding or selection into completed delivery.');
B(stats,'B20','Source snapshot availability and repeated seller/customer dependence remain limitations.');

guide.getRange('B:B').format.columnWidth=27;guide.getRange('C:C').format.columnWidth=114;
const definitions=[
 ['Source','Olist Brazilian e-commerce, version 2. '+data.source],
 ['Reporting population','All 99,441 orders are represented through aggregates. No row sample is used.'],
 ['SLA eligible','Delivered status, valid purchase/promise/delivery timestamps, delivery >= purchase, promise date >= purchase date.'],
 ['Late order','Actual delivery calendar date is after the promised calendar date. Same-day arrival is on time.'],
 ['Unknown outcomes','2,971 orders are outside the completed SLA denominator. Unknown is never silently counted as on time.'],
 ['Mean delivery days','Sum of elapsed delivery days for eligible orders divided by the same eligible-order count.'],
 ['Distance','Straight-line distance between postcode centroids, not a road route or measured courier travel time.'],
 ['Review timing','Each previous dayâ€™s approvals are screened once at 09:00 next day; known completed deliveries leave the queue.'],
 ['Review minutes','4 base +2 multiple items +3 multiple sellers +1 any interstate/unknown-state movement; illustrative assumptions.'],
 ['Planner limits','Default 120 pooled minutes, maximum 30 reviews, maximum 5 reviews per primary seller, per batch.'],
 ['Priority points','Within-batch raw-score rank becomes ordinal points. Points are not reliable probabilities or expected savings.'],
 ['Model limitation','The first August test failed. The updated model and planner reuse August; independent new-period evidence is unavailable.'],
 ['Scenario selector','Chooses an already executed Python scenario. It updates linked summaries/daily tables, without re-optimizing in Excel.'],
 ['Staffing calculator','Editable uniform minutes and count limit calculate a simple upper bound, separately from saved optimizer queues.'],
 ['Refresh data','Run reporting_data.py, then excel/build_workbook.mjs. Source snapshots and exact results are recorded locally.'],
 ['Operations run',data.operation_run],['Model run',data.model_run],['Database SHA-256',data.provenance.database_sha256],
 ['Cloud role','Azure Data Factory copied files. Standalone Databricks Free Edition processed Delta tables via an explicit local handoff.'],
 ['This workbook','Uses local verified reporting exports. It is not connected to live cloud data or a courier system.']
];values(guide,'B5:C24',definitions);guide.getRange('B5:B24').format.font.bold=true;
section(guide,'B27','Reconciliation checks');
values(guide,'B29:D29',[['Measure','Observed','Expected']]);header(guide,'B29:D29');
values(guide,'B30:B35',[['All source orders'],['SLA eligible'],['Late deliveries'],['Outside SLA cohort'],['State order coverage'],['Base optimized reviews']]);
fx(guide,'C30:C35',[["='Overview'!G7"],["='Overview'!C7"],["='Overview'!C8"],["='Overview'!G8"],
 [`=SUM('Sources'!C${stateStart}:C${stateEnd})`],[`=SUMIFS('Sources'!I${scenarioStart}:I${scenarioEnd},'Sources'!B${scenarioStart}:B${scenarioEnd},"capacity_120_cost_1",'Sources'!C${scenarioStart}:C${scenarioEnd},"optimized")`]]);
values(guide,'D30:D35',[99441,96470,6534,2971,99441,721].map(v=>[v]));
values(guide,'E29:E29',[['Difference']]);header(guide,'E29:E29');fx(guide,'E30:E35',Array.from({length:6},(_,i)=>[`=C${30+i}-D${30+i}`]));
guide.getRange('E30:E35').conditionalFormats.add('cellIs',{operator:'notEqual',formula:0,format:{fill:'#FEE2E2',font:{color:'#B91C1C',bold:true}}});
guide.getRange('C30:E35').setNumberFormat('#,##0');guide.getRange('C29:C35').format.columnWidth=114;
// The note column is wide; reconciliation uses a compact independent area instead.
guide.getRange('C29:E35').format.columnWidth=20;
guide.getRange('C5:C24').format.wrapText=false;
// Keep explanations readable across otherwise empty columns without merging.

wb.recalculate();
const base=review.getRange('C13:F13').values[0];
if(base[0]!==721||base[1]!==3314||base[2]!==24||base[3]!==79)throw new Error('Default review summary mismatch: '+JSON.stringify(base));
if(overview.getRange('C7:C8').values.map(r=>r[0]).join(',')!=='96470,6534')throw new Error('SLA headline mismatch');
if(review.getRange('K29').values[0][0]!==30)throw new Error('Staffing formula mismatch');
// Exercise changes, zero and blank boundaries and restore the delivered defaults.
B(review,'C6','capacity_60_cost_1');wb.recalculate();
if(review.getRange('C13').values[0][0]!==378)throw new Error('Scenario selection failed to recalculate');
B(review,'C6','capacity_0_cost_1');wb.recalculate();
if(review.getRange('C13').values[0][0]!==0)throw new Error('Zero-capacity scenario failed');
B(review,'C6','capacity_120_cost_1');B(review,'K25',60);wb.recalculate();
if(review.getRange('K29').values[0][0]!==15)throw new Error('Staffing input change failed');
B(review,'K25',0);wb.recalculate();if(review.getRange('K29').values[0][0]!==0)throw new Error('Zero staffing capacity failed');
B(review,'K26',null);wb.recalculate();if(review.getRange('K29').values[0][0]!=='n.a.')throw new Error('Blank staffing input hidden');
B(review,'K25',120);B(review,'K26',4);wb.recalculate();
const inspection=await wb.inspect({kind:'table',range:'Review capacity!B12:I16',include:'values,formulas',tableMaxRows:5,tableMaxCols:8,maxChars:4500});
await fs.writeFile(path.join(out,'workbook_inspection.ndjson'),inspection.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},maxChars:5000});
await fs.writeFile(path.join(out,'formula_error_scan.ndjson'),errors.ndjson);
console.log(errors.ndjson);
for(const [s,r] of [[overview,'B2:P38'],[overview,'B43:P71'],[review,'B2:P20'],[review,'B22:P54'],[stats,'B2:L21'],[source,'B2:H33'],[source,'B75:O81'],[source,'B904:P908'],[guide,'B2:P24'],[guide,'B27:E35']]){
 const image=await wb.render({sheetName:s.name,range:r,scale:1.3,format:'png'});
 await fs.writeFile(path.join(out,`${s.name.replaceAll(' ','_')}_${r.split(':')[0]}.png`),new Uint8Array(await image.arrayBuffer()));
}
const file=await SpreadsheetFile.exportXlsx(wb);await file.save(path.join(out,'Delivery_Operations.xlsx'));
await fs.writeFile(path.join(out,'AUTHORING_VERIFICATION.json'),JSON.stringify({engine:'@oai/artifact-tool',sourceOrders:99441,
 worksheets:5,scenarioChangeVerified:true,zeroCapacityVerified:true,staffingInputAndBlankVerified:true,
 operationsRun:data.operation_run,modelRun:data.model_run,nativeExcelVerification:'Pending'},null,2));
console.log(JSON.stringify({xlsx:path.join(out,'Delivery_Operations.xlsx'),sheets:5,sourceOrders:99441}));
