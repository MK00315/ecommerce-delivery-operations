param([Parameter(Mandatory=$true)][int]$DesktopProcessId)
$ErrorActionPreference = 'Stop'
$deliveryProject = Split-Path -Parent $PSScriptRoot
$deliveryWorkspace = Split-Path -Parent (Split-Path -Parent $deliveryProject)
$deliveryClientRoot = Join-Path $deliveryWorkspace 'work/powerbi-tools/clients'
Add-Type -Path (Join-Path $deliveryClientRoot 'microsoft.analysisservices/lib/net8.0/Microsoft.AnalysisServices.Core.dll')
Add-Type -Path (Join-Path $deliveryClientRoot 'microsoft.analysisservices/lib/net8.0/Microsoft.AnalysisServices.Tabular.dll')
Add-Type -Path (Join-Path $deliveryClientRoot 'microsoft.analysisservices.adomdclient/lib/net8.0/Microsoft.AnalysisServices.AdomdClient.dll')
$deliveryEngine = @(Get-CimInstance Win32_Process -Filter "Name='msmdsrv.exe'" | Where-Object { $_.ParentProcessId -eq $DesktopProcessId })
if ($deliveryEngine.Count -ne 1) { throw 'Expected one engine belonging to the selected report process.' }
$deliveryEnginePath = [regex]::Match($deliveryEngine[0].CommandLine, '-s "([^"]+)"').Groups[1].Value
$deliveryPort = (Get-Content -LiteralPath (Join-Path $deliveryEnginePath 'msmdsrv.port.txt') -Encoding Unicode -Raw).Trim()
if ($deliveryPort -notmatch '^\d+$') { throw 'Invalid report engine port.' }
$deliveryServer = [Microsoft.AnalysisServices.Tabular.Server]::new()
$deliveryServer.Connect("Data Source=localhost:$deliveryPort")
$deliveryMatchingDatabases = @($deliveryServer.Databases | Where-Object {
    $_.Model.Tables.Count -eq 8 -and $_.Model.Tables.Name -contains 'Orders' -and $_.Model.Tables.Name -contains 'Daily Reviews'
})
if ($deliveryMatchingDatabases.Count -ne 1) { throw "Expected one delivery model; catalogs=$($deliveryServer.Databases.Count), matching=$($deliveryMatchingDatabases.Count)." }
$deliveryDatabase = $deliveryMatchingDatabases[0]
$deliveryConnection = [Microsoft.AnalysisServices.AdomdClient.AdomdConnection]::new("Data Source=localhost:$deliveryPort;Initial Catalog=$($deliveryDatabase.ID)")
$deliveryConnection.Open()
$deliveryQueries = [ordered]@{
    Headlines = 'EVALUATE ROW("Orders",[Source Orders],"Eligible",[Eligible Deliveries],"Late",[Late Deliveries],"Unknown",[Outside SLA Cohort],"LateRate",[Late Rate],"MeanDays",[Mean Delivery Days])'
    StateSP = 'EVALUATE CALCULATETABLE(ROW("Orders",[Source Orders],"Eligible",[Eligible Deliveries],"Late",[Late Deliveries],"APFixed",[Diagnostic AP]),States[State]="SP")'
    March2018 = 'EVALUATE CALCULATETABLE(ROW("Orders",[Source Orders],"Eligible",[Eligible Deliveries],"Late",[Late Deliveries]),''Calendar''[Month Key]=201803)'
    DefaultPlan = 'EVALUATE ROW("Reviews",[Optimized Reviews],"KnownLate",[Optimized Known Late],"Unknown",[Optimized Unknown],"Minutes",[Optimized Minutes],"Denominator",[Queue Known Late])'
    SixtyMinutes = 'EVALUATE CALCULATETABLE(ROW("Reviews",[Optimized Reviews],"KnownLate",[Optimized Known Late],"Minutes",[Optimized Minutes]),Scenarios[Scenario Key]="capacity_60_cost_1")'
    ZeroCapacity = 'EVALUATE CALCULATETABLE(ROW("Reviews",[Optimized Reviews],"KnownLate",[Optimized Known Late],"Minutes",[Optimized Minutes]),Scenarios[Scenario Key]="capacity_0_cost_1")'
    Policies = 'EVALUATE SUMMARIZECOLUMNS(Policies[Policy],"Reviews",[Review Count],"KnownLate",[Known Late Reviewed],"Capture",[Known Late Capture])'
    Statistics = 'EVALUATE SUMMARIZECOLUMNS(Statistics[Comparison],"Adjusted",[Adjusted Difference pp],"Low",[CI Low pp],"High",[CI High pp],"HolmP",[Holm p Value])'
    Evidence = 'EVALUATE ROW("AP",[Diagnostic AP],"BaselineAP",[Constant AP],"ROC",[Diagnostic ROC AUC],"Brier",[Diagnostic Brier])'
}
$deliveryResults = [ordered]@{}
foreach ($deliveryQuery in $deliveryQueries.GetEnumerator()) {
    $deliveryCommand = $deliveryConnection.CreateCommand()
    $deliveryCommand.CommandText = $deliveryQuery.Value
    $deliveryReader = $deliveryCommand.ExecuteReader()
    $deliveryRows = [System.Collections.Generic.List[object]]::new()
    while ($deliveryReader.Read()) {
        $deliveryRow = [ordered]@{}
        for ($deliveryIndex=0; $deliveryIndex -lt $deliveryReader.FieldCount; $deliveryIndex++) {
            $deliveryColumn = $deliveryReader.GetName($deliveryIndex).Trim('[',']')
            $deliveryRow[$deliveryColumn] = if ($deliveryReader.IsDBNull($deliveryIndex)) { $null } else { $deliveryReader.GetValue($deliveryIndex) }
        }
        $deliveryRows.Add($deliveryRow)
    }
    $deliveryReader.Close()
    $deliveryResults[$deliveryQuery.Key] = $deliveryRows.ToArray()
}
$deliveryConnection.Close()
$deliveryServer.Disconnect()
$deliveryHeadlines=$deliveryResults.Headlines[0]
if ($deliveryHeadlines.Orders -ne 99441 -or $deliveryHeadlines.Eligible -ne 96470 -or $deliveryHeadlines.Late -ne 6534 -or $deliveryHeadlines.Unknown -ne 2971) { throw 'Source totals mismatch.' }
if ([math]::Abs($deliveryHeadlines.LateRate-6534/96470) -gt 1e-12) { throw 'Late rate denominator mismatch.' }
if ($deliveryResults.StateSP[0].Orders -ne 41746 -or $deliveryResults.StateSP[0].Eligible -ne 40494 -or $deliveryResults.StateSP[0].Late -ne 1820) { throw 'State relationship/filter mismatch.' }
if ($deliveryResults.March2018[0].Orders -ne 7211 -or $deliveryResults.March2018[0].Eligible -ne 7003 -or $deliveryResults.March2018[0].Late -ne 1328) { throw 'Calendar relationship/filter mismatch.' }
$deliveryDefault=$deliveryResults.DefaultPlan[0]
if ($deliveryDefault.Reviews -ne 721 -or $deliveryDefault.KnownLate -ne 79 -or $deliveryDefault.Unknown -ne 24 -or $deliveryDefault.Minutes -ne 3314 -or $deliveryDefault.Denominator -ne 406) { throw 'Planner defaults or denominator deduplication mismatch.' }
if ($deliveryResults.SixtyMinutes[0].Reviews -ne 378 -or $deliveryResults.SixtyMinutes[0].KnownLate -ne 46 -or $deliveryResults.SixtyMinutes[0].Minutes -ne 1676) { throw 'Scenario filter mismatch.' }
if ($deliveryResults.ZeroCapacity[0].Reviews -ne 0 -or $deliveryResults.ZeroCapacity[0].Minutes -ne 0) { throw 'Zero-capacity mismatch.' }
if ($deliveryResults.Policies.Count -ne 4 -or $deliveryResults.Statistics.Count -ne 4) { throw 'Expected four policies and contrasts.' }
if ([math]::Abs($deliveryResults.Evidence[0].AP-0.09010847209) -gt 1e-10 -or $deliveryResults.StateSP[0].APFixed -ne $deliveryResults.Evidence[0].AP) { throw 'Fixed diagnostic scope mismatch.' }
$deliveryRecord=[ordered]@{CheckedAt=(Get-Date).ToString('o');Passed=$true;NativeEngine='Power BI Desktop Analysis Services';AuthoredTables=8;DAXMeasures=30;ReadOnlyQueries=$deliveryQueries.Count;Results=$deliveryResults}
$deliveryOutput=Join-Path $deliveryWorkspace 'outputs/Delivery_PowerBI/docs/NATIVE_DAX_VERIFICATION.json'
$deliveryRecord | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $deliveryOutput -Encoding utf8
Write-Output ($deliveryRecord | ConvertTo-Json -Depth 12)
