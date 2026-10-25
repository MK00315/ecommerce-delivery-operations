"""Portable native PBIP/TMDL delivery model and four PBIR report pages."""
from __future__ import annotations

import base64
import argparse
import csv
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "powerbi/project"
MODEL = OUT / "Delivery.SemanticModel"
REPORT = OUT / "Delivery.Report"
DEFINITION = REPORT / "definition"
TABLES, MEASURES, VISUALS = {}, {}, []
INK, MUTED, SKY, BLUE, PALE = "#16324F", "#566F85", "#0EA5E9", "#0369A1", "#F3F9FE"
PAGES = [("d4100000000000000001", "Overview"), ("d4100000000000000002", "Delivery patterns"),
         ("d4100000000000000003", "Review planning"), ("d4100000000000000004", "Model and statistics")]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def table(name, columns, rows, measures=()):
    TABLES[name] = {"columns": columns, "rows": rows}
    MEASURES[name] = list(measures)


def load_tables():
    source = ROOT / "reports/reporting"
    data = json.loads((source / "workbook_inputs.json").read_text())
    model = json.loads((ROOT / "reports/modeling/latest_completed.json").read_text())
    columns = [("Order ID", "string"), ("Purchase Date", "dateTime"), ("Customer State", "string"),
               ("Final Status", "string"), ("SLA Eligible", "int64"), ("Late Flag", "int64"),
               ("Delivery Days", "double"), ("Item Count", "int64"), ("Seller Count", "int64"),
               ("Promised Days", "int64"), ("Distance Km", "double"), ("Distance Complete", "int64")]
    rows = []
    with (source / "orders.csv").open(newline="", encoding="utf-8") as stream:
        for raw in csv.DictReader(stream):
            row = [None if raw[c] == "" else int(float(raw[c])) if t == "int64" else float(raw[c]) if t == "double" else raw[c] for c, t in columns]
            distance, complete, count = row[10], row[11], row[7]
            row += ["Unknown/incomplete" if not complete else "<=500 km" if distance <= 500 else
                    "500-1,000 km" if distance <= 1000 else "1,000-2,000 km" if distance <= 2000 else ">2,000 km",
                    "Missing basket" if count == 0 else "1 item" if count == 1 else "2-3 items" if count <= 3 else "4+ items"]
            rows.append(row)
    columns += [("Distance Group", "string"), ("Basket Group", "string")]
    assert len(rows) == 99441 and len({r[0] for r in rows}) == 99441
    assert sum(r[4] for r in rows) == 96470 and sum(r[5] or 0 for r in rows) == 6534
    assert sum(r[5] is None for r in rows) == 2971
    table("Orders", columns, rows, [
        ("Source Orders", "COUNTROWS('Orders')", "#,##0"),
        ("Eligible Deliveries", "SUM('Orders'[SLA Eligible])", "#,##0"),
        ("Late Deliveries", "SUM('Orders'[Late Flag])", "#,##0"),
        ("On-time Deliveries", "[Eligible Deliveries]-[Late Deliveries]", "#,##0"),
        ("Late Rate", "DIVIDE([Late Deliveries],[Eligible Deliveries])", "0.00%"),
        ("Outside SLA Cohort", "[Source Orders]-[Eligible Deliveries]", "#,##0"),
        ("Mean Delivery Days", "AVERAGE('Orders'[Delivery Days])", "0.00"),
        ("Median Delivery Days", "MEDIAN('Orders'[Delivery Days])", "0.00"),
        ("Complete Distance Share", "DIVIDE(CALCULATE([Eligible Deliveries],'Orders'[Distance Complete]=1),[Eligible Deliveries])", "0.0%"),
    ])
    first, last = min(r[1] for r in rows), max(r[1] for r in rows)
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    dates = [start + timedelta(days=i) for i in range((end-start).days + 1)]
    table("Calendar", [("Date", "dateTime"), ("Month", "string"), ("Month Key", "int64"), ("Year", "int64")],
          [[d.isoformat(), d.strftime("%b %Y"), d.year*100+d.month, d.year] for d in dates])
    table("States", [("State", "string")], [[r["state"]] for r in data["states"]])
    scenario_rows = []
    for r in data["scenarios"]:
        if r["policy"] == "optimized":
            scenario_rows.append([r["scenario"], f"{r['capacity_minutes']} min / {r['cost_multiplier']:.2f}x time",
                                  r["capacity_minutes"], r["cost_multiplier"]])
    table("Scenarios", [("Scenario Key", "string"), ("Scenario", "string"), ("Minutes per Batch", "int64"), ("Time Multiplier", "double")], scenario_rows, [
        ("Selected Scenario", 'SELECTEDVALUE(\'Scenarios\'[Scenario Key],"capacity_120_cost_1")', ""),
        ("Scenario Minutes", 'VAR s=[Selected Scenario] RETURN CALCULATE(MAX(\'Scenarios\'[Minutes per Batch]),\'Scenarios\'[Scenario Key]=s)', "#,##0"),
    ])
    policy_keys = ["optimized", "risk_first", "priority_per_minute", "oldest_first"]
    policy_names = ["Constrained optimizer", "Highest risk first", "Priority per minute", "Oldest approval first"]
    table("Policies", [("Policy Key", "string"), ("Policy", "string"), ("Policy Order", "int64")],
          [[k,n,i] for i,(k,n) in enumerate(zip(policy_keys,policy_names),1)])
    daily_columns = [("Scenario Key", "string"), ("Policy Key", "string"), ("Screening Date", "dateTime"),
                     ("Candidates", "int64"), ("Candidate Known Late", "int64"), ("Selected", "int64"),
                     ("Used Minutes", "int64"), ("Unknown Selected", "int64"), ("Known Late Selected", "int64"),
                     ("Priority Points", "double"), ("Selected Known Outcomes", "int64"), ("Unused Minutes", "int64")]
    daily_rows = [[r["scenario"],r["policy"],r["batch_cutoff"][:10],r["candidate_orders"],r["candidate_known_late"],
                   r["selected_orders"],r["used_minutes"],r["selected_unknown_outcomes"],r["selected_known_late"],
                   r["priority_points"],r["selected_known_outcomes"],r["unused_minutes"]] for r in data["daily"]]
    measures = []
    for name, col in [("Review Count","Selected"),("Review Minutes","Used Minutes"),("Unknown Reviews","Unknown Selected"),
                       ("Known Late Reviewed","Known Late Selected"),("Review Priority Points","Priority Points")]:
        measures.append((name,f"VAR s=[Selected Scenario] RETURN CALCULATE(SUM('Daily Reviews'[{col}]),'Scenarios'[Scenario Key]=s)","#,##0.0" if col=="Priority Points" else "#,##0"))
    measures += [
        ("Queue Known Late", "VAR s=[Selected Scenario] RETURN CALCULATE(SUMX(VALUES('Daily Reviews'[Screening Date]),CALCULATE(MAX('Daily Reviews'[Candidate Known Late]))),'Scenarios'[Scenario Key]=s)", "#,##0"),
        ("Known Late Capture", "DIVIDE([Known Late Reviewed],[Queue Known Late])", "0.0%"),
        ("Optimized Reviews", 'CALCULATE([Review Count],\'Policies\'[Policy Key]="optimized")', "#,##0"),
        ("Optimized Known Late", 'CALCULATE([Known Late Reviewed],\'Policies\'[Policy Key]="optimized")', "#,##0"),
        ("Optimized Unknown", 'CALCULATE([Unknown Reviews],\'Policies\'[Policy Key]="optimized")', "#,##0"),
        ("Optimized Minutes", 'CALCULATE([Review Minutes],\'Policies\'[Policy Key]="optimized")', "#,##0"),
    ]
    table("Daily Reviews", daily_columns, daily_rows, measures)
    table("Statistics", [("Comparison","string"),("Adjusted pp","double"),("Lower Bound pp","double"),("Upper Bound pp","double"),
                          ("Holm p","double"),("Contrast Orders","int64"),("Excluded","int64")],
          [[r["label"],r["adjusted_difference"]*100,r["ci_low"]*100,r["ci_high"]*100,r["holm_p_value"],r["orders"],r["excluded_from_contrast"]] for r in data["contrasts"]],
          [("Adjusted Difference pp","MAX('Statistics'[Adjusted pp])","+0.00;-0.00;0.00"),
           ("CI Low pp","MAX('Statistics'[Lower Bound pp])","+0.00;-0.00;0.00"),
           ("CI High pp","MAX('Statistics'[Upper Bound pp])","+0.00;-0.00;0.00"),
           ("Holm p Value","MAX('Statistics'[Holm p])","0.00E+00")])
    diagnostic = model["august_diagnostic"]
    table("Model Evidence", [("AP","double"),("Baseline AP","double"),("ROC AUC","double"),("Adjusted Brier","double"),
                             ("Raw Brier","double"),("Constant Brier","double"),("Refit Orders","int64"),("Inputs","int64")],
          [[diagnostic["average_precision"],diagnostic["late_rate"],diagnostic["roc_auc"],diagnostic["brier_score"],
            model["raw_august_diagnostic"]["brier_score"],model["august_baselines"]["constant_calibration_rate"]["brier_score"],83848,31]],
          [("Diagnostic AP","MAX('Model Evidence'[AP])","0.0000"),("Constant AP","MAX('Model Evidence'[Baseline AP])","0.0000"),
           ("Diagnostic ROC AUC","MAX('Model Evidence'[ROC AUC])","0.0000"),("Diagnostic Brier","MAX('Model Evidence'[Adjusted Brier])","0.0000")])
    return data


def model_files():
    (MODEL / "definition/tables").mkdir(parents=True, exist_ok=True)
    write(MODEL / "definition.pbism", {"version":"4.2","settings":{}})
    (MODEL / "definition/database.tmdl").write_text("database Delivery\n\tcompatibilityLevel: 1600\n",encoding="utf-8")
    (MODEL / "definition/model.tmdl").write_text("model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n\nannotation __PBI_TimeIntelligenceEnabled = 0\n\n"+
        "\n".join(f"ref table '{n}'" for n in TABLES)+"\n",encoding="utf-8")
    for name, spec in TABLES.items():
        columns, rows = spec["columns"], spec["rows"]
        if {c.casefold() for c,_ in columns} & {m.casefold() for m,_,_ in MEASURES[name]}:
            raise ValueError(f"Column/measure naming collision in {name}")
        blob=base64.b64encode(zlib.compress(json.dumps(rows,separators=(",",":"),ensure_ascii=False).encode(),wbits=-15)).decode()
        names=", ".join(json.dumps(c) for c,_ in columns)
        conversions=", ".join('{'+json.dumps(c)+', '+{"int64":"Int64.Type","double":"type number","string":"type text","dateTime":"type date"}[t]+'}' for c,t in columns)
        m=f'let\n    Snapshot=Json.Document(Binary.Decompress(Binary.FromText("{blob}",BinaryEncoding.Base64),Compression.Deflate)),\n    Rows=Table.FromRows(Snapshot,{{{names}}}),\n    Typed=Table.TransformColumnTypes(Rows,{{{conversions}}},"en-US")\nin\n    Typed'
        text=f"table '{name}'\n"
        for measure, expression, fmt in MEASURES[name]:
            text+=f"\n\tmeasure '{measure}' = {expression}\n"
            if fmt:text+=f"\t\tformatString: {fmt}\n"
        for col, typ in columns:
            text+=f"\n\tcolumn '{col}'\n\t\tdataType: {typ}\n\t\tsourceColumn: {col}\n\t\tsummarizeBy: none\n"
            if typ=="dateTime":text+="\t\tformatString: dd MMM yyyy\n"
            elif typ=="double":text+="\t\tformatString: 0.0000\n"
            elif typ=="int64":text+="\t\tformatString: #,##0\n"
            if col.endswith(" Key") or col=="Order ID":text+="\t\tisHidden\n"
            if (name,col) in [("Calendar","Date"),("States","State"),("Scenarios","Scenario Key"),("Policies","Policy Key")]:text+="\t\tisKey\n"
            sort={('Calendar','Month'):'Month Key',('Policies','Policy'):'Policy Order'}.get((name,col))
            if sort:text+=f"\t\tsortByColumn: '{sort}'\n"
        text+=f"\n\tpartition '{name}' = m\n\t\tmode: import\n\t\tsource =\n"+"\n".join("\t\t\t"+line for line in m.splitlines())+"\n"
        (MODEL / "definition/tables" / f"{name}.tmdl").write_text(text,encoding="utf-8")
    relationships=[]
    for fact, column, dim, key in [("Orders","Purchase Date","Calendar","Date"),("Orders","Customer State","States","State"),
                                    ("Daily Reviews","Screening Date","Calendar","Date"),("Daily Reviews","Scenario Key","Scenarios","Scenario Key"),
                                    ("Daily Reviews","Policy Key","Policies","Policy Key")]:
        ident=uuid.uuid5(uuid.NAMESPACE_URL,"delivery-"+fact+column)
        relationships.append(f"relationship {ident}\n\tfromColumn: '{fact}'.'{column}'\n\ttoColumn: '{dim}'.'{key}'\n\tcrossFilteringBehavior: oneDirection\n")
    (MODEL / "definition/relationships.tmdl").write_text("\n".join(relationships),encoding="utf-8")
    write(OUT / "docs/MODEL_INVENTORY.json",{n:{"rows":len(s["rows"]),"columns":s["columns"],"measures":MEASURES[n]} for n,s in TABLES.items()})


def lit(value):
    value = str(value).lower() if isinstance(value,bool) else str(value)+"D" if isinstance(value,(int,float)) else "'"+str(value).replace("'","''")+"'"
    return {"expr":{"Literal":{"Value":value}}}


def fill(color):return {"solid":{"color":lit(color)}}
def obj(**props):return [{"properties":props}]
def field(table,col,measure=False):return {"Measure" if measure else "Column":{"Expression":{"SourceRef":{"Entity":table}},"Property":col}}
def proj(table,col,measure=False):return {"field":field(table,col,measure),"queryRef":table+"."+col,"nativeQueryRef":col}


def visual(page,key,typ,x,y,w,h,roles=None,title=None,objects=None,sort=None,white=True):
    ident=hashlib.sha256((page+key).encode()).hexdigest()[:20]
    if any(v['id']==ident for v in VISUALS):
        raise ValueError(f"Duplicate page/visual key: {page}/{key}")
    chrome={"background":obj(show=lit(white),color=fill("#FFFFFF"),transparency=lit(0)),
            "border":obj(show=lit(white),color=fill("#D8EAF7"),radius=lit(9),width=lit(1)),
            "padding":obj(**{p:lit(0 if typ=='textbox' and not white else 8 if typ=='textbox' else 12) for p in ['top','bottom','left','right']}),
            "title":obj(show=lit(bool(title)),text=lit(title or ""),fontSize=lit(13),fontColor=fill(INK),fontFamily=lit("Segoe UI Semibold")),
            "subTitle":obj(show=lit(False)),
            "visualHeader":obj(show=lit(True))}
    body={"visualType":typ,"visualContainerObjects":chrome}
    if roles:
        body["query"]={"queryState":{r:{"projections":p} for r,p in roles.items()}}
        if sort:body["query"]["sortDefinition"]={"sort":[{"field":sort[0],"direction":sort[1]}],"isDefaultSort":False}
    if objects:body["objects"]=objects
    record={"$schema":"https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.9.0/schema.json",
            "name":ident,"position":{"x":x,"y":y,"z":len(VISUALS)+1,"height":h,"width":w,"tabOrder":len(VISUALS)},"visual":body}
    write(DEFINITION / "pages" / page / "visuals" / ident / "visual.json",record)
    VISUALS.append({"page":page,"id":ident,"key":key,"type":typ})


def text(page,key,content,x,y,w,h,size=14,bold=False,white=False):
    paragraphs=[{"textRuns":[{"value":line,"textStyle":{"fontFamily":"Segoe UI Semibold" if bold else "Segoe UI","fontSize":f"{size}px","color":INK}}]} for line in content.split("\n")]
    visual(page,key,"textbox",x,y,w,h,objects={"general":obj(paragraphs=paragraphs)},white=white)


def header(page,title,subtitle):
    text(page,"brand","Delivery Operations",25,10,760,60,29,True)
    text(page,"title",title,25,90,820,60,26,True)
    text(page,"subtitle",subtitle,25,151,1500,42,13)
    visual(page,"navigation","pageNavigator",810,20,758,56,white=False,
           objects={"layout":obj(rowCount=lit(1),columnCount=lit(4),cellPadding=lit(6)),
                    "text":obj(show=lit(True),fontSize=lit(11),fontColor=fill(BLUE))})
    text(page,"footer","Historical public Olist data. Observational findings and experimental review scenarios; no prevented-delay or savings claim.",25,1015,1545,32,11)


def card(page,key,table,measure,title,x):
    visual(page,key,"card",x,218,360,120,{"Values":[proj(table,measure,True)]},title,
           objects={"labels":obj(fontSize=lit(33),color=fill(BLUE),labelDisplayUnits=lit(1)),"categoryLabels":obj(show=lit(False))})


def slicer(page,key,table,col,title,x,y,w):
    visual(page,key,"slicer",x,y,w,80,{"Values":[proj(table,col)]},objects={
        "data":obj(mode=lit("Dropdown")),"header":obj(show=lit(True),text=lit(title),textSize=lit(11)),
        "items":obj(textSize=lit(11)),"selection":obj(singleSelect=lit(True),selectAllCheckboxEnabled=lit(False))})


def chart(page,key,typ,category,measure,title,x,y,w,h):
    visual(page,key,typ,x,y,w,h,{"Category":[proj(*category)],"Y":[proj(measure[0],measure[1],True)]},title,
           sort=(field(category[0],category[1]),"Ascending") if typ=="lineChart" else (field(measure[0],measure[1],True),"Descending"),
           objects={"categoryAxis":obj(show=lit(True),fontSize=lit(11),labelColor=fill(MUTED)),
                    "valueAxis":obj(show=lit(True),fontSize=lit(10),labelColor=fill(MUTED)),
                    "dataPoint":obj(defaultColor=fill(SKY)),"legend":obj(show=lit(False)),
                    "labels":obj(show=lit(typ=="barChart"),fontSize=lit(10),labelDisplayUnits=lit("0")),"subheader":obj(show=lit(False))})


def data_table(page,key,bindings,title,x,y,w,h):
    visual(page,key,"tableEx",x,y,w,h,{"Values":[proj(*b) for b in bindings]},title,
           objects={"columnHeaders":obj(fontSize=lit(10),bold=lit(True),fontColor=fill(INK),backColor=fill("#E0F2FE"),wordWrap=lit(True),autoSizeColumnWidth=lit(True)),
                    "values":obj(fontSize=lit(11),fontColor=fill(INK),backColorPrimary=fill("#FFFFFF"),backColorSecondary=fill("#F0F9FF"),wordWrap=lit(True)),
                    "grid":obj(gridVertical=lit(False),gridHorizontal=lit(True),rowPadding=lit(5)),"total":obj(totals=lit(False))})


def report_files():
    write(OUT / "Delivery.pbip",{"$schema":"https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json","version":"1.0","artifacts":[{"report":{"path":"Delivery.Report"}}],"settings":{"enableAutoRecovery":True}})
    write(REPORT / "definition.pbir",{"$schema":"https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json","version":"4.0","datasetReference":{"byPath":{"path":"../Delivery.SemanticModel"}}})
    write(REPORT / ".platform",{"$schema":"https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata":{"type":"Report","displayName":"Delivery Operations"},"config":{"version":"2.0","logicalId":str(uuid.uuid5(uuid.NAMESPACE_URL,'delivery-operations-report'))}})
    write(DEFINITION / "version.json",{"$schema":"https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json","version":"2.0.0"})
    # Portable envelope references a built-in Desktop theme; all data/pages are new.
    (REPORT / "StaticResources/SharedResources").mkdir(parents=True, exist_ok=True)
    template=json.loads((ROOT / "powerbi/assets/report_envelope.json").read_text())
    theme_name="DeliverySkyBlue.json"
    template["themeCollection"]["customTheme"]["name"]=theme_name
    template["resourcePackages"]=[p for p in template["resourcePackages"] if p["name"]!="RegisteredResources"]+[
        {"name":"RegisteredResources","type":"RegisteredResources","items":[{"name":theme_name,"path":theme_name,"type":"CustomTheme"}]}]
    write(DEFINITION / "report.json",template)
    write(REPORT / "StaticResources/RegisteredResources" / theme_name,{"name":theme_name,"dataColors":[SKY,BLUE,"#38BDF8","#64748B","#0F766E"],
        "background":"#FFFFFF","foreground":INK,"tableAccent":BLUE})
    for page,name in PAGES:
        write(DEFINITION / "pages" / page / "page.json",{"$schema":"https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
            "name":page,"displayName":name,"displayOption":"FitToPage","height":1050,"width":1600,
            "objects":{"background":obj(color=fill(PALE),transparency=lit(0)),"outspace":obj(color=fill(PALE),transparency=lit(0))}})
    write(DEFINITION / "pages/pages.json",{"$schema":"https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json","pageOrder":[p for p,_ in PAGES],"activePageName":PAGES[0][0]})
    p=PAGES[0][0]
    header(p,"Delivery overview","All 99,441 source orders are retained. Delivery rates use the completed SLA-eligible cohort.")
    slicer(p,"state","States","State","Customer state",1080,100,480)
    for x,key,measure,title in [(32,"orders","Source Orders","Source orders"),(424,"eligible","Eligible Deliveries","Eligible completed deliveries"),
                               (816,"late","Late Rate","Late rate"),(1208,"days","Mean Delivery Days","Mean delivery days")]:card(p,key,"Orders",measure,title,x)
    chart(p,"monthly","lineChart",("Calendar","Month"),("Orders","Late Deliveries"),"Late deliveries by purchase month",32,370,940,300)
    chart(p,"state_volume","barChart",("States","State"),("Orders","Eligible Deliveries"),"Eligible completed orders by state",1000,370,568,620)
    data_table(p,"monthly_table",[("Calendar","Month"),("Orders","Source Orders",True),("Orders","Eligible Deliveries",True),("Orders","Late Deliveries",True),("Orders","Late Rate",True)],"Monthly delivery summary",32,698,940,292)
    p=PAGES[1][0]
    header(p,"Delivery patterns","Distance uses postcode-centroid approximations. Unknown or incomplete geocoding remains a separate group.")
    slicer(p,"state","States","State","Customer state",1080,100,480)
    for x,key,measure,title in [(32,"eligible","Eligible Deliveries","Eligible deliveries"),(424,"rate","Late Rate","Late rate"),
                               (816,"distance_coverage","Complete Distance Share","Complete distance coverage"),(1208,"median","Median Delivery Days","Median delivery days")]:card(p,key,"Orders",measure,title,x)
    chart(p,"distance","barChart",("Orders","Distance Group"),("Orders","Late Rate"),"Late rate by maximum basket distance",32,370,752,270)
    chart(p,"basket","barChart",("Orders","Basket Group"),("Orders","Late Rate"),"Late rate by basket size",812,370,756,270)
    data_table(p,"states",[("States","State"),("Orders","Eligible Deliveries",True),("Orders","Late Deliveries",True),("Orders","Late Rate",True),("Orders","Median Delivery Days",True)],"State cohorts and delivery outcomes",32,668,1536,322)
    p=PAGES[2][0]
    header(p,"Review planning","Saved Python scenarios. Default: 120 pooled minutes, 30 reviews, 5 per primary seller, per batch.")
    slicer(p,"scenario","Scenarios","Scenario","Executed scenario (single selection)",1040,100,528)
    for x,key,measure,title in [(32,"reviews","Optimized Reviews","Optimized reviews"),(424,"late","Optimized Known Late","Known late outcomes reviewed"),
                               (816,"unknown","Optimized Unknown","Unknown outcomes reviewed"),(1208,"minutes","Optimized Minutes","Minutes used across batches")]:card(p,key,"Daily Reviews",measure,title,x)
    chart(p,"late_policies","barChart",("Policies","Policy"),("Daily Reviews","Known Late Reviewed"),"Known late outcomes queued, by policy",32,370,752,270)
    chart(p,"review_policies","barChart",("Policies","Policy"),("Daily Reviews","Review Count"),"Review volume under the same limits",812,370,756,270)
    data_table(p,"daily",[("Daily Reviews","Screening Date"),("Daily Reviews","Optimized Reviews",True),("Daily Reviews","Optimized Known Late",True),
                          ("Daily Reviews","Optimized Unknown",True),("Daily Reviews","Optimized Minutes",True)],"Optimized daily review queue",32,668,980,322)
    text(p,"assumptions","Review times are illustrative.\n4 base minutes, +2 multiple items,\n+3 multiple sellers, +1 interstate/unknown.\n\nUnknown outcomes consume capacity.\nPriority points are ordinal model ranks.\nAugust is a reused diagnostic.\nThese counts are not prevented delays.",1040,668,528,322,15,white=True)
    p=PAGES[3][0]
    header(p,"Model and statistics","Fixed historical evidence. Updated August scores are reused diagnostics, not independent new-period validation.")
    for x,key,measure,title in [(32,"ap","Diagnostic AP","Model average precision"),(424,"prior","Constant AP","Constant ranking baseline AP"),
                               (816,"auc","Diagnostic ROC AUC","Diagnostic ROC-AUC"),(1208,"brier","Diagnostic Brier","Adjusted probability Brier score")]:card(p,key,"Model Evidence",measure,title,x)
    data_table(p,"stats",[("Statistics","Comparison"),("Statistics","Adjusted Difference pp",True),("Statistics","CI Low pp",True),
                          ("Statistics","CI High pp",True),("Statistics","Holm p Value",True)],"Month-adjusted associations (percentage points)",32,370,1536,252)
    text(p,"model_limits","Prediction limits\n\nStatic logistic regression, 31 inputs, 83,848 refit orders.\nThe first boosted-tree model failed its independent August test.\nUpdated ranking gains are modest and probabilities are unreliable.\nAdjusted Brier is worse than raw and constant scores.\nNo fresh independent period or real intervention evidence is available.",32,650,752,340,17,white=True)
    text(p,"methods","Methods and data path\n\nStatistics: completed deliveries, purchase-month effects,\npurchase-week clustered intervals and Holm correction.\nAssociations are exploratory; intervals are marginal.\nAzure Data Factory -> verified local handoff -> Databricks Delta.\nTraining, statistics and planning ran locally with Python.\nThis report imports a portable snapshot; no live cloud refresh.",812,650,756,340,17,white=True)
    write(OUT / "docs/VISUAL_MANIFEST.json",VISUALS)


def main(layout_only=False):
    data=load_tables()
    if not layout_only:model_files()
    report_files()
    (OUT / ".gitignore").write_text("**/.pbi/\n*.log\n",encoding="utf-8")
    write(OUT / "docs/SOURCE_VERIFICATION.json",{"source_orders":99441,"eligible":96470,"late":6534,"outside_sla":2971,
        "relationships":5,"tables":len(TABLES),"measures":sum(len(m) for m in MEASURES.values()),"pages":4,
        "operations_run":data["operation_run"],"provenance":data["provenance"],"native_verification":"Pending"})
    print(json.dumps({"output":str(OUT),"tables":len(TABLES),"measures":sum(len(m) for m in MEASURES.values()),"pages":4,"visuals":len(VISUALS)},indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout-only',action='store_true',help='Preserve the imported native model when changing only PBIR visuals')
    main(parser.parse_args().layout_only)
